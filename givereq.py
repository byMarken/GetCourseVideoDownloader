"""Скачивание уроков из предварительно собранного списка курсов."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from playwright.async_api import Frame, async_playwright

from gcpd import try_download_with_quality as gcpd_main
from login import ensure_login_active
from utils_config import get_env_config

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

    clean = re.sub(
        r"\b(Просмотрено|Пройдено|Завершено)\b",
        "",
        name,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s+", " ", clean).strip()
    return re.sub(r"[\\/*?:\"<>|]", "_", clean)


async def _click_modal_if_present(frame: Frame) -> None:
    """Закрывает модалку, если она появилась."""

    modal = frame.locator(".mst-root .cnf-root, .cnf-root")
    try:
        await modal.wait_for(state="attached", timeout=2500)
    except Exception:  # noqa: BLE001
        return

    for selector in [".cnf-button--decline", ".cnf-button--confirm"]:
        button = frame.locator(selector)
        if await button.count():
            await frame.evaluate(
                "(el)=>el.click()",
                await button.first.element_handle(),
            )
            break

    try:
        await modal.wait_for(state="detached", timeout=4000)
    except Exception:  # noqa: BLE001
        pass


async def _click_play(frame: Frame) -> None:
    """Нажимает кнопку Play."""

    button = frame.locator(".fsn-main-btn.fsn-main-btn--play, .fsn-main-btn")
    await button.first.wait_for(state="attached", timeout=8000)
    await frame.evaluate("(el)=>el.click()", await button.first.element_handle())


async def _handle_player_frame(frame: Frame) -> bool:
    """Обрабатывает iframe с плеером."""

    if not await frame.query_selector(".vpl-root"):
        return False
    if not await frame.query_selector(".mst-root"):
        return False

    try:
        await frame.evaluate(
            """
            (() => {
                const els = document.querySelectorAll('video, audio');
                for (const el of els) {
                    el.muted = true;
                    el.volume = 0;
                    el.pause = () => {};
                    try { el.play(); } catch {}
                }
                const ctxs = (window.AudioContext || window.webkitAudioContext);
                if (ctxs) {
                    try {
                        const ctx = new ctxs();
                        ctx.suspend();
                    } catch(e) {}
                }
            })();
            """
        )
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Не удалось заглушить звук: {exc}")

    await _click_modal_if_present(frame)
    await _click_play(frame)
    return True


async def process_lesson(
    browser,
    course_title: str,
    lesson: dict[str, Any],
    save_root: str,
    quality: str,
) -> None:
    """Находит запросы m3u8 и скачивает видео."""

    page = await browser.new_page()
    await page.goto(lesson["url"])

    login_required_url = "https://school.example/cms/system/login?required=true"
    was_login_page = page.url.startswith(login_required_url)
    login_restored = await ensure_login_active(page)

    if not login_restored:
        await browser.close()
        return

    if was_login_page:
        print("🔁 Повторная загрузка урока после авторизации...")
        await page.goto(lesson["url"])
        await asyncio.sleep(2)

    best: dict[str, tuple[int, str]] = {}

    async def on_request(request):  # noqa: ANN001 - тип объекта playwright
        url = request.url
        if "/api/playlist/media/" in url and "user-cdn=" in url:
            video_id = _extract_video_id(url)
            provider = _extract_provider(url)
            score = _provider_score(provider)

            if quality.lower() == "auto":
                for resolution in ["1080", "720", "480", "360"]:
                    if f"/{resolution}?" in url:
                        best[video_id] = (score, url)
                        break
            else:
                best[video_id] = (score, replace_quality(url, quality))

    page.on("request", lambda req: asyncio.create_task(on_request(req)))

    for frame in [fr for fr in page.frames if "vhcdn.com" in (fr.url or "")]:
        try:
            await _handle_player_frame(frame)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Ошибка фрейма: {exc}")

    await asyncio.sleep(5)
    await page.close()

    videos = [url for _, url in sorted(best.values(), key=lambda item: -item[0])]
    if not videos:
        print(f"⚠️ Видео не найдено: {lesson['title']}")
        return

    course_path = os.path.join(save_root, course_title)
    os.makedirs(course_path, exist_ok=True)
    safe_title = sanitize_filename(lesson["title"])

    if len(videos) == 1:
        await gcpd_main(videos[0], os.path.join(course_path, safe_title))
        return

    lesson_path = os.path.join(course_path, safe_title)
    os.makedirs(lesson_path, exist_ok=True)
    for index, video_url in enumerate(videos, start=1):
        await gcpd_main(video_url, os.path.join(lesson_path, f"video_{index}"))


async def main() -> None:
    """Читает courses.json и скачивает все уроки."""

    cfg = get_env_config()
    save_root = cfg["courses_save_path"]
    quality = cfg["quality"]

    if not os.path.exists("courses.json") or os.path.getsize("courses.json") == 0:
        print("⚠️ Файл courses.json пустой или отсутствует.")
        print(
            "💡 Укажите ссылку на плейлист в .env и запустите givelinks.py "
            "для создания списка курсов."
        )
        return

    with open("courses.json", "r", encoding="utf-8") as courses_file:
        courses = json.load(courses_file)

    async with async_playwright() as playwright:
        browser = await playwright.firefox.launch_persistent_context(
            USER_DATA_DIR,
            headless=cfg["headless"],
        )

        for course in courses:
            print(f"\n📚 Курс: {course['course_title']}")
            for lesson in course["lessons"]:
                await process_lesson(
                    browser,
                    course["course_title"],
                    lesson,
                    save_root,
                    quality,
                )

        await browser.close()




if __name__ == "__main__":
    asyncio.run(main())
