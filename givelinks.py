import asyncio
import json
import re
import os
from pathlib import Path
from playwright.async_api import async_playwright
from utils_config import get_env_config
from login import ensure_login_active

USER_DATA_DIR = "session_data"
OUTPUT_FILE = "courses.json"


def clean_title(title: str) -> str:
    title = re.sub(r'\b(Просмотрено|Пройдено|Завершено)\b', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s+', ' ', title).strip()
    return title


async def main():
    cfg = get_env_config()

    playlist_url = cfg.get("playlist_url")
    if not playlist_url or not isinstance(playlist_url, str) or not playlist_url.startswith("http"):
        raise ValueError("❌ В .env не найден параметр PLAYLIST_URL с корректным URL")

    output_path = OUTPUT_FILE

    async with async_playwright() as p:
        browser = await p.firefox.launch_persistent_context(
            USER_DATA_DIR,
            headless=cfg.get("headless", True)
        )

        page = await browser.new_page()
        await page.goto(playlist_url)

        if not await ensure_login_active(page):
            await browser.close()
            return

        print("🔍 Загружаю список курсов...")
        await page.wait_for_selector("tr.training-row")

        rows = await page.query_selector_all("tr.training-row")
        courses = []

        for row in rows:
            title_el = await row.query_selector("span.stream-title")
            course_title = await title_el.inner_text() if title_el else "Без названия"
            link_el = await row.query_selector("a")
            href = await link_el.get_attribute("href") if link_el else "#"
            if href.startswith("/"):
                href = f"https://school.beilbei.ru{href}"
            courses.append((clean_title(course_title), href))

        all_courses = []

        for course_title, href in courses:
            print(f"\n📚 {course_title}")
            await page.goto(href)

            try:
                await page.wait_for_selector("ul.lesson-list li", timeout=5000)
                lessons = await page.query_selector_all("ul.lesson-list li")
            except:
                lessons = []

            lessons_data = []
            for lesson in lessons:
                title_el = await lesson.query_selector("div.link.title")
                lesson_title = await title_el.inner_text() if title_el else "Без названия"
                lesson_title = clean_title(lesson_title)

                link_el = await lesson.query_selector("a")
                lesson_href = await link_el.get_attribute("href") if link_el else "#"
                if lesson_href.startswith("/"):
                    lesson_href = f"https://school.beilbei.ru{lesson_href}"

                print(f"   🎬 {lesson_title}")
                lessons_data.append({"title": lesson_title, "url": lesson_href})

            all_courses.append({
                "course_title": course_title,
                "lessons": lessons_data
            })

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_courses, f, ensure_ascii=False, indent=4)

        print(f"\n✅ Курсы сохранены в {output_path}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
