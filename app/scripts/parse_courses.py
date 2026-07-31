from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Playwright, async_playwright

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.utils.browser import launch_browser
from app.utils.console import configure_console_output
from app.utils.paths import data_dir

_OUTPUT_DIR = data_dir()
_OUTPUT_FILE = str(_OUTPUT_DIR / "courses.json")
LESSON_LIST_TIMEOUT: float = 5_000.0

configure_console_output()


def clean_title(title: str) -> str:
    cleaned = re.sub(
        r"\b(Просмотрено|Пройдено|Завершено)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


class _FragmentParser(HTMLParser):
    """Извлекает текст первого элемента (tag, class) и первый href из фрагмента HTML."""

    def __init__(self, tag: str, class_name: str) -> None:
        super().__init__()
        self._tag = tag
        self._class_names = set(class_name.split())
        self._depth = 0
        self._collecting = False
        self._parts: list[str] = []
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "a" and self.href is None:
            self.href = attr_map.get("href")
        classes = set((attr_map.get("class") or "").split())
        if tag == self._tag and self._class_names.issubset(classes):
            self._collecting = True
            self._depth = 1
        elif self._collecting:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._collecting:
            self._depth -= 1
            if self._depth == 0:
                self._collecting = False

    def handle_data(self, data: str) -> None:
        if self._collecting:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts).strip()


def parse_course_row(html: str) -> tuple[str, str]:
    """Извлекает (название, href) из HTML строки `tr.training-row`."""
    parser = _FragmentParser("span", "stream-title")
    parser.feed(html)
    title = parser.text() or "Без названия"
    return clean_title(title), parser.href or "#"


def parse_lesson_item(html: str) -> tuple[str, str]:
    """Извлекает (название, url) из HTML элемента `ul.lesson-list li`."""
    parser = _FragmentParser("div", "link title")
    parser.feed(html)
    title = parser.text() or "Без названия"
    return clean_title(title), parser.href or "#"


async def ensure_authenticated(
    playwright: Playwright,
    playlist_url: str,
    wait_for_login: Callable[[], Awaitable[None]] | None = None,
) -> None:
    browser = await launch_browser(
        playwright,
        headless=True,
    )
    page = browser.pages[0] if browser.pages else await browser.new_page()
    await page.goto(playlist_url)
    needs_auth: bool = "login" in page.url.lower()
    await browser.close()

    if not needs_auth:
        print("[OK] Авторизация активна.")
        return

    print("[INFO] Требуется авторизация. Выполните вход в браузере.")

    browser = await launch_browser(
        playwright,
        headless=False,
    )
    login_page = browser.pages[0] if browser.pages else await browser.new_page()
    await login_page.goto(playlist_url)

    if wait_for_login:
        await wait_for_login()
    else:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            input,
            "После успешного входа нажмите Enter...",
        )

    await browser.close()
    print("[OK] Авторизация выполнена, продолжаем работу.")


async def parse_courses(
    playwright: Playwright,
    playlist_url: str,
    on_course_parsed: Callable[[str, int], Awaitable[None]] | None = None,
) -> list[dict]:
    browser = await launch_browser(
        playwright,
        headless=True,
    )
    page = browser.pages[0] if browser.pages else await browser.new_page()
    await page.goto(playlist_url)

    print("[INFO] Загружаю список курсов...")
    print("   → Ищу список курсов на странице...")
    try:
        await page.wait_for_selector("tr.training-row", timeout=5_000)
        rows = await page.query_selector_all("tr.training-row")
    except Exception:
        rows = []

    if rows:
        courses: list[dict[str, str]] = []
        for row in rows:
            course_title, href = parse_course_row(await row.inner_html())
            href = urljoin(playlist_url, href)
            courses.append({"title": course_title, "href": href})

        all_courses = []
        for course in courses:
            print(f"\n[COURSE] {course['title']}")
            await page.goto(course["href"])

            try:
                await page.wait_for_selector("ul.lesson-list li", timeout=LESSON_LIST_TIMEOUT)
                lesson_elements = await page.query_selector_all("ul.lesson-list li")
            except Exception:
                lesson_elements = []

            lessons_data = []
            for lesson in lesson_elements:
                lesson_title, lesson_href = parse_lesson_item(await lesson.inner_html())
                lesson_href = urljoin(playlist_url, lesson_href)
                print(f"   [LESSON] {lesson_title}")
                lessons_data.append({"title": lesson_title, "url": lesson_href})

            all_courses.append({"course_title": course["title"], "lessons": lessons_data})

            if on_course_parsed:
                await on_course_parsed(course["title"], len(lessons_data))

        await browser.close()
        return all_courses

    lessons = await page.query_selector_all("ul.lesson-list li")

    if lessons:
        print("   → Найдены уроки на текущей странице (один курс)")
        course_title_el = await page.query_selector("h1")
        single_course_title = await course_title_el.inner_text() if course_title_el else "Курс"
        single_course_title = clean_title(single_course_title)

        lesson_items: list[dict[str, str]] = []
        single_courses: list[dict[str, object]] = [
            {
                "course_title": single_course_title,
                "lessons": lesson_items,
            }
        ]

        for lesson in lessons:
            single_lesson_title, single_lesson_href = parse_lesson_item(await lesson.inner_html())
            single_lesson_href = urljoin(playlist_url, single_lesson_href)
            print(f"   [LESSON] {single_lesson_title}")
            lesson_items.append({"title": single_lesson_title, "url": single_lesson_href})

        if on_course_parsed:
            await on_course_parsed(single_course_title, len(lesson_items))

        await browser.close()
        return single_courses

    print("   ⚠ Не удалось найти курсы или уроки на странице.")
    await browser.close()
    return []


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Парсинг курсов GetCourse — извлечение списка уроков в JSON.",
    )
    parser.add_argument(
        "playlist_url",
        help="URL плейлиста курсов на GetCourse (https://…)",
    )
    args = parser.parse_args()

    playlist_url: str = args.playlist_url
    if not playlist_url.startswith("http"):
        print("[ERROR] URL плейлиста должен начинаться с http:// или https://")
        sys.exit(1)

    print(f"[INFO] Парсинг плейлиста: {playlist_url}")

    async with async_playwright() as playwright:
        await ensure_authenticated(playwright, playlist_url)
        courses = await parse_courses(playwright, playlist_url)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = Path(_OUTPUT_FILE)
    output_path.write_text(
        json.dumps(courses, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )

    print(f"\n[OK] Курсы сохранены в {_OUTPUT_FILE}.")


if __name__ == "__main__":
    asyncio.run(main())
