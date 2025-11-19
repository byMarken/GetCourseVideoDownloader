"""Скрипт для выгрузки списка курсов и уроков из GetCourse."""

from __future__ import annotations

import asyncio
import json
import re

from playwright.async_api import async_playwright

from login import ensure_login_active
from utils_config import get_env_config

USER_DATA_DIR = "session_data"
OUTPUT_FILE = "courses.json"


def clean_title(title: str) -> str:
    """Удаляет служебные пометки из названия и нормализует пробелы."""

    cleaned = re.sub(
        r"\b(Просмотрено|Пройдено|Завершено)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


async def main() -> None:
    """Основная точка входа для получения курсов."""

    cfg = get_env_config()
    playlist_url = cfg.get("playlist_url")
    if (
        not playlist_url
        or not isinstance(playlist_url, str)
        or not playlist_url.startswith("http")
    ):
        raise ValueError("❌ В .env не найден параметр PLAYLIST_URL с корректным URL")

    async with async_playwright() as playwright:
        browser = await playwright.firefox.launch_persistent_context(
            USER_DATA_DIR,
            headless=cfg.get("headless", True),
        )

        page = await browser.new_page()
        await page.goto(playlist_url)

        if not await ensure_login_active(page):
            await browser.close()
            return

        print("🔍 Загружаю список курсов...")
        await page.wait_for_selector("tr.training-row")

        rows = await page.query_selector_all("tr.training-row")
        courses: list[tuple[str, str]] = []

        for row in rows:
            title_el = await row.query_selector("span.stream-title")
            course_title = await title_el.inner_text() if title_el else "Без названия"
            link_el = await row.query_selector("a")
            href = await link_el.get_attribute("href") if link_el else "#"
            if href.startswith("/"):
                href = f"https://school.example{href}"
            courses.append((clean_title(course_title), href))

        all_courses = []

        for course_title, href in courses:
            print(f"\n📚 {course_title}")
            await page.goto(href)

            try:
                await page.wait_for_selector("ul.lesson-list li", timeout=5000)
                lessons = await page.query_selector_all("ul.lesson-list li")
            except Exception:  # noqa: BLE001
                lessons = []

            lessons_data = []
            for lesson in lessons:
                title_el = await lesson.query_selector("div.link.title")
                lesson_title = await title_el.inner_text() if title_el else "Без названия"
                lesson_title = clean_title(lesson_title)

                link_el = await lesson.query_selector("a")
                lesson_href = await link_el.get_attribute("href") if link_el else "#"
                if lesson_href.startswith("/"):
                    lesson_href = f"https://school.example{lesson_href}"

                print(f"   🎬 {lesson_title}")
                lessons_data.append({"title": lesson_title, "url": lesson_href})

            all_courses.append({"course_title": course_title, "lessons": lessons_data})

        with open(OUTPUT_FILE, "w", encoding="utf-8") as output_file:
            json.dump(all_courses, output_file, ensure_ascii=False, indent=4)

        print(
            f"\n✅ Курсы сохранены в {OUTPUT_FILE}. Можете отредактировать файл для "
            "сохранения конкретных курсов. Потом запустите givereq.py"
        )
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
