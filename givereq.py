import os
import re
import json
import asyncio
from typing import Dict, Any
from playwright.async_api import async_playwright, Frame
from gcpd import try_download_with_quality as gcpd_main
from utils_config import get_env_config
from login import ensure_login_active


USER_DATA_DIR = "session_data"
PREF = {"cloudflare": 3, "integrosproxy": 2}


def _extract_video_id(url: str) -> str:
    """Извлекает ID видео из URL."""
    match = re.search(r"/api/playlist/media/([^/?#]+)/", url)
    return match.group(1) if match else url


def _extract_provider(url: str) -> str:
    """Извлекает CDN-провайдера (cloudflare, integrosproxy и т.д.)."""
    match = re.search(r"[?&]user-cdn=([^&]+)", url)
    return match.group(1) if match else ""


def _provider_score(provider: str) -> int:
    """Рейтинг провайдера — для выбора лучшего URL."""
    return PREF.get(provider, 1)


def replace_quality(url: str, target_quality: str) -> str:
    """Заменяет качество в URL."""
    return re.sub(r"/(360|480|720|1080)\?", f"/{target_quality}?", url)


def sanitize_filename(name: str) -> str:
    """Удаляет запрещённые символы и пометки 'Просмотрено'."""
    clean = re.sub(r'\b(Просмотрено|Пройдено|Завершено)\b', '', name, flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return re.sub(r'[\\/*?:"<>|]', "_", clean)


# ---------- Работа с плеером ----------
async def _click_modal_if_present(frame: Frame) -> None:
    """Закрывает модалку, если она появилась."""
    cnf = frame.locator(".mst-root .cnf-root, .cnf-root")
    try:
        await cnf.wait_for(state="attached", timeout=2500)
    except:
        return

    for sel in [".cnf-button--decline", ".cnf-button--confirm"]:
        btn = frame.locator(sel)
        if await btn.count():
            await frame.evaluate("(el)=>el.click()", await btn.first.element_handle())
            break

    try:
        await cnf.wait_for(state="detached", timeout=4000)
    except:
        pass


async def _click_play(frame: Frame) -> None:
    """Нажимает кнопку Play."""
    btn = frame.locator(".fsn-main-btn.fsn-main-btn--play, .fsn-main-btn")
    await btn.first.wait_for(state="attached", timeout=8000)
    await frame.evaluate("(el)=>el.click()", await btn.first.element_handle())


async def _handle_player_frame(frame: Frame) -> bool:
    """Обрабатывает iframe с плеером."""
    if not await frame.query_selector(".vpl-root"):
        return False
    if not await frame.query_selector(".mst-root"):
        return False

    try:
        await frame.evaluate("""
            (() => {
                const els = document.querySelectorAll('video, audio');
                for (const el of els) {
                    el.muted = true;
                    el.volume = 0;
                    el.pause = () => {};   // блокируем включение звука
                    try { el.play(); } catch {}
                }
                const ctxs = (window.AudioContext || window.webkitAudioContext);
                if (ctxs) {
                    try {
                        const ctx = new ctxs();
                        ctx.suspend(); // отключаем весь аудиоконтекст
                    } catch(e) {}
                }
            })();
        """)
    except Exception as e:
        print(f"⚠️ Не удалось заглушить звук: {e}")

    await _click_modal_if_present(frame)
    await _click_play(frame)
    return True


async def process_lesson(p, browser, course_title: str, lesson: Dict[str, Any],
                         save_root: str, quality: str) -> None:
    """Находит запросы m3u8 и скачивает видео."""
    page = await browser.new_page()
    await page.goto(lesson["url"])

    # Проверяем авторизацию
    was_login_page = page.url.startswith("https://school.example/cms/system/login?required=true")
    login_restored = await ensure_login_active(page)

    if not login_restored:
        await browser.close()
        return

    if was_login_page:
        print("🔁 Повторная загрузка урока после авторизации...")
        await page.goto(lesson["url"])
        await asyncio.sleep(2)

    best: Dict[str, tuple[int, str]] = {}

    async def on_req(req):
        url = req.url
        if "/api/playlist/media/" in url and "user-cdn=" in url:
            vid = _extract_video_id(url)
            prov = _extract_provider(url)
            score = _provider_score(prov)

            if quality.lower() == "auto":
                for q in ["1080", "720", "480", "360"]:
                    if f"/{q}?" in url:
                        best[vid] = (score, url)
                        break
            else:
                best[vid] = (score, replace_quality(url, quality))

    page.on("request", lambda r: asyncio.create_task(on_req(r)))

    # Обрабатываем все плееры на странице
    for fr in [f for f in page.frames if "vhcdn.com" in (f.url or "")]:
        try:
            await _handle_player_frame(fr)
        except Exception as e:
            print(f"⚠️ Ошибка фрейма: {e}")

    await asyncio.sleep(5)
    await page.close()

    videos = [u for _, u in sorted(best.values(), key=lambda x: -x[0])]
    if not videos:
        print(f"⚠️ Видео не найдено: {lesson['title']}")
        return

    # Создание папок
    course_path = os.path.join(save_root, course_title)
    os.makedirs(course_path, exist_ok=True)

    safe_title = sanitize_filename(lesson["title"])

    if len(videos) == 1:
        await gcpd_main(videos[0], os.path.join(course_path, safe_title))
    else:
        lesson_path = os.path.join(course_path, safe_title)
        os.makedirs(lesson_path, exist_ok=True)
        for i, v in enumerate(videos, 1):
            await gcpd_main(v, os.path.join(lesson_path, f"video_{i}"))

async def main() -> None:
    cfg = get_env_config()
    save_root = cfg["courses_save_path"]
    quality = cfg["quality"]

    # Загружаем курсы
    with open("courses.json", "r", encoding="utf-8") as f:
        courses = json.load(f)
    async with async_playwright() as p:
        browser = await p.firefox.launch_persistent_context(
            USER_DATA_DIR,
            headless=cfg["headless"]
        )

        for course in courses:
            print(f"\n📚 Курс: {course['course_title']}")
            for lesson in course["lessons"]:
                await process_lesson(p, browser, course["course_title"], lesson, save_root, quality)

        await browser.close()



if __name__ == "__main__":
    asyncio.run(main())
