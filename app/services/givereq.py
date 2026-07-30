from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from typing import Any

from pathlib import Path
from urllib.parse import urljoin

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.utils.ffmpeg import get_ffmpeg_path
from app.utils.console import configure_console_output
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

USER_DATA_DIR = "session_data"
_COURSES_PATH = Path(_PROJECT_ROOT) / "app" / "data" / "courses.json"

configure_console_output()


def _extract_quality(url: str) -> int:
    path = url.split("?", 1)[0]
    numeric_parts = [part for part in path.split("/") if part.isdigit()]
    if not numeric_parts:
        return 0
    return int(numeric_parts[-1])


def sanitize_filename(name: str) -> str:
    clean = re.sub(
        r"\b(Просмотрено|Пройдено|Завершено)\b",
        "",
        name,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s+", " ", clean).strip()
    return re.sub(r"[\\/*?:\"<>|]", "_", clean)


def _parse_master_playlist(text: str, master_url: str) -> dict[int, str]:
    qualities = {}
    lines = text.strip().splitlines()
    last_resolution = None

    for line in lines:
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            match = re.search(r"RESOLUTION=\d+x(\d+)", line)
            last_resolution = int(match.group(1)) if match else None
        elif line and not line.startswith("#"):
            if not line.startswith("http"):
                line = urljoin(master_url, line)
            quality = _extract_quality(line)
            if quality == 0 and last_resolution:
                quality = last_resolution
            if quality > 0:
                qualities[quality] = line
            last_resolution = None

    return qualities


def _select_quality_url(qualities: dict[int, str], quality_filter: str) -> str | None:
    if not qualities:
        return None

    available = sorted(qualities)

    if not quality_filter or quality_filter == "auto":
        return qualities[available[-1]]

    target = int(quality_filter)

    if target in qualities:
        return qualities[target]

    below = [q for q in available if q < target]
    if below:
        return qualities[below[-1]]

    return qualities[available[0]]


async def _countdown(seconds: int, message: str = "Ожидание") -> None:
    for i in range(seconds, 0, -1):
        print(f"\r  ⏳ {message}: {i} сек.", end="", flush=True)
        await asyncio.sleep(1)
    print(f"\r  ⏳ {message}: 0 сек.", flush=True)


async def _download_video(playlist_url: str, output_path: str) -> bool:
    import aiohttp
    import shutil
    import tempfile

    output_mp4 = output_path + ".mp4"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://school.beilbei.ru/",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(playlist_url) as resp:
            playlist = await resp.text()

        segment_urls = [
            line.strip() for line in playlist.splitlines()
            if line.strip() and not line.startswith("#") and (".bin" in line or ".ts" in line)
        ]
        total = len(segment_urls)
        if not total:
            print("  ⚠ Нет сегментов")
            return False

        tmpdir = tempfile.mkdtemp()
        sem = asyncio.Semaphore(10)

        downloaded_count = 0
        last_report_time = 0.0

        async def download_seg(idx: int, seg_url: str) -> str | None:
            nonlocal downloaded_count, last_report_time
            async with sem:
                for attempt in range(3):
                    try:
                        async with session.get(seg_url) as resp:
                            data = await resp.read()
                        path = os.path.join(tmpdir, f"{idx:05d}.bin")
                        with open(path, "wb") as f:
                            f.write(data)
                        downloaded_count += 1
                        now = time.monotonic()
                        if now - last_report_time >= 2.0:
                            last_report_time = now
                            pct = downloaded_count * 100 // total
                            print(f"\r  Сегменты: {downloaded_count}/{total} ({pct}%)", end="", flush=True)
                        return path
                    except Exception:
                        if attempt == 2:
                            return None
                        await asyncio.sleep(1)

        tasks = [download_seg(i, u) for i, u in enumerate(segment_urls)]
        results = await asyncio.gather(*tasks)
        segments = sorted(r for r in results if r)

        if not segments:
            print("  ⚠ Не скачано ни одного сегмента")
            return False

        ts_file = output_mp4.replace(".mp4", ".ts")
        with open(ts_file, "wb") as out:
            for seg in segments:
                with open(seg, "rb") as f:
                    out.write(f.read())

        shutil.rmtree(tmpdir, ignore_errors=True)

        print(f"\r  Сегментов: {len(segments)}/{total} ({len(segments)*100//total}%)")

        ffmpeg_path = get_ffmpeg_path()
        process = await asyncio.create_subprocess_exec(
            ffmpeg_path,
            "-y",
            "-i", ts_file,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            output_mp4,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            process.kill()
            print("  ✗ Ошибка: ffmpeg завис (таймаут 5 мин)")
            os.remove(ts_file)
            return False
        os.remove(ts_file)
        if process.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")[-300:]
            print(f"  ✗ Ошибка конвертации")
            return False

        return True


async def _open_page_with_retries(
    page: Any, url: str, attempts: int = 3, purpose: str = "страницу"
) -> None:
    """Open a page reliably when the school responds slowly."""
    last_error: PlaywrightError | None = None

    for attempt in range(1, attempts + 1):
        try:
            # "commit" is enough to detect redirects to the login page and avoids
            # waiting for all lesson resources before authentication is checked.
            await page.goto(url, wait_until="commit", timeout=60_000)
            return
        except (PlaywrightTimeoutError, PlaywrightError) as error:
            last_error = error
            if attempt < attempts:
                print(f"  ⚠ Не удалось открыть {purpose}. Повтор {attempt}/{attempts - 1}...")
                await asyncio.sleep(attempt * 3)

    raise RuntimeError(
        "Не удалось открыть страницу урока: сайт не отвечает. "
        "Проверьте интернет, доступность школы и повторите попытку."
    ) from last_error


async def _authentication_required(page: Any) -> bool:
    """Wait briefly for a possible redirect to the school's login page."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except PlaywrightError:
        # The page may keep loading player resources, but its redirect URL is
        # already available and is enough for the authentication check.
        pass

    await page.wait_for_timeout(500)
    current_url = page.url.lower()
    return "login" in current_url or "required=true" in current_url


async def ensure_authenticated(playwright: Any, url: str) -> bool:
    browser = await playwright.firefox.launch_persistent_context(
        USER_DATA_DIR,
        headless=True,
    )
    try:
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await _open_page_with_retries(
            page, url, purpose="страницу для проверки авторизации"
        )
        needs_auth = await _authentication_required(page)
    finally:
        await browser.close()

    if not needs_auth:
        print("  ✓ Авторизация активна")
        return True

    print("\n  🔐 Требуется авторизация. Открываю браузер для входа...\n")
    await asyncio.sleep(5)
    browser = await playwright.firefox.launch_persistent_context(
        USER_DATA_DIR,
        headless=False,
    )
    login_page = browser.pages[0] if browser.pages else await browser.new_page()
    await _open_page_with_retries(login_page, url, purpose="страницу входа")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, input, "  После успешного входа нажмите Enter...")

    await browser.close()
    print("  ✓ Авторизация выполнена. Продолжаем.\n")
    return True


async def process_lesson(
    browser,
    course_title: str,
    lesson: dict[str, Any],
    save_root: str,
    quality_filter: str = "auto",
    playwright: Any | None = None,
) -> bool:
    lesson_title = lesson["title"]
    lesson_url = lesson["url"]
    print(f"\n  ▶ {lesson_title}")

    page = await browser.new_page()

    master_urls_seen: set[str] = set()
    master_playlists: list[tuple[str, str]] = []
    last_arrival = 0.0

    async def _on_response(response):
        nonlocal last_arrival
        url = response.url
        if "/api/playlist/master/" not in url or url in master_urls_seen:
            return
        master_urls_seen.add(url)
        try:
            text = await response.text()
            master_playlists.append((url, text))
            last_arrival = time.monotonic()
        except Exception:
            pass

    page.on("response", lambda resp: asyncio.create_task(_on_response(resp)))

    try:
        await _open_page_with_retries(page, lesson_url, purpose="страницу урока")
    except RuntimeError as error:
        print(f"  ✗ {error}")
        await page.close()
        return False

    if await _authentication_required(page):
        print("\n  ⚠ Страница запросила авторизацию")
        if not playwright:
            print("  ⚠ Передайте playwright для повторной авторизации")
            await page.close()
            return False

        print("  🔐 Открываю браузер для ручного входа...")
        auth_browser = await playwright.firefox.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
        )
        auth_page = auth_browser.pages[0] if auth_browser.pages else await auth_browser.new_page()
        await _open_page_with_retries(auth_page, lesson_url, purpose="страницу входа")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, input, "  После успешного входа нажмите Enter...")
        await auth_browser.close()
        print("  ✓ Авторизация выполнена. Продолжаем.")

        master_urls_seen.clear()
        master_playlists.clear()
        last_arrival = 0.0
        try:
            await _open_page_with_retries(page, lesson_url, purpose="страницу урока")
        except RuntimeError as error:
            print(f"  ✗ {error}")
            await page.close()
            return False

        if await _authentication_required(page):
            print("  ⚠ Авторизация не подтверждена")
            await page.close()
            return False

    start_time = time.monotonic()
    while True:
        if time.monotonic() - start_time >= 30:
            break
        if master_playlists and time.monotonic() - last_arrival >= 5:
            break
        await asyncio.sleep(0.5)

    await page.close()

    if not master_playlists:
        print("  ⚠ Master playlist не получен")
        return False

    downloaded = False
    for idx, (master_url, master_text) in enumerate(master_playlists, start=1):
        qualities = _parse_master_playlist(master_text, master_url)
        selected_url = _select_quality_url(qualities, quality_filter)

        if not selected_url:
            print("  ⚠ Не удалось подобрать качество")
            continue

        q = _extract_quality(selected_url)

        course_path = os.path.join(save_root, course_title)
        os.makedirs(course_path, exist_ok=True)
        safe_title = sanitize_filename(lesson_title)

        if len(master_playlists) > 1:
            video_dir = os.path.join(course_path, safe_title)
            os.makedirs(video_dir, exist_ok=True)
            downloaded = await _download_video(
                selected_url, os.path.join(video_dir, f"video_{idx}")
            ) or downloaded
        else:
            downloaded = await _download_video(
                selected_url, os.path.join(course_path, safe_title)
            ) or downloaded

        print()

    return downloaded


async def main() -> int:
    parser = argparse.ArgumentParser(description="Скачивание уроков из courses.json")
    parser.add_argument("--quality", default="auto", choices=["auto", "1080", "720", "480", "360"])
    parser.add_argument("--save-path", default="downloads", dest="save_path")
    parser.add_argument("--lessons-file", help="JSON-файл с выбранными уроками")
    args = parser.parse_args()

    save_root = args.save_path
    quality_setting = args.quality

    if args.lessons_file:
        with open(args.lessons_file, "r", encoding="utf-8") as f:
            entries = json.load(f)
    else:
        if not _COURSES_PATH.exists() or _COURSES_PATH.stat().st_size == 0:
            print("  ⚠ Файл courses.json пустой или отсутствует.")
            return 1

        with open(_COURSES_PATH, "r", encoding="utf-8") as courses_file:
            courses = json.load(courses_file)

        entries = []
        for course in courses:
            for lesson in course["lessons"]:
                entries.append({
                    "course_title": course["course_title"],
                    "lesson": lesson,
                })

    async with async_playwright() as playwright:
        if entries:
            first_url = entries[0]["lesson"]["url"]
            await ensure_authenticated(playwright, first_url)

        browser = await playwright.firefox.launch_persistent_context(
            USER_DATA_DIR,
            headless=True,
        )

        downloaded_lessons = 0
        for entry in entries:
            course_title = entry["course_title"]
            lesson = entry["lesson"]
            downloaded = await process_lesson(
                browser,
                course_title,
                lesson,
                save_root,
                quality_setting,
                playwright=playwright,
            )
            downloaded_lessons += int(downloaded)

        await browser.close()

    if downloaded_lessons == len(entries):
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
