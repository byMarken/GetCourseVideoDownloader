from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from playwright.async_api import Page, Playwright, async_playwright

from getcourse_downloader.application.ports.discovery import (
    AuthRequiredCallback,
    CourseDiscoveredCallback,
    VideoCheckCallback,
)
from getcourse_downloader.domain.errors import ExternalServiceError
from getcourse_downloader.domain.models import Course, Lesson
from getcourse_downloader.infrastructure.browser.playwright import PlaywrightBrowserFactory
from getcourse_downloader.infrastructure.getcourse.video_probe import GetCourseVideoProbe

MAX_STREAMS = 500

_STREAM_REFERENCE_RE = re.compile(
    r"(?:(?:https?:)?//[^\"'<>\s\\]+)?/(?:pl/)?teach/control/stream/"
    r"(?:view/id/\d+|view\?[^\"'<>\s\\]*\bid=\d+[^\"'<>\s\\]*)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _StreamLink:
    url: str
    title: str | None = None


def clean_title(title: str) -> str:
    cleaned = re.sub(
        r"\b(Просмотрено|Пройдено|Завершено)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


class _FragmentParser(HTMLParser):
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
    parser = _FragmentParser("span", "stream-title")
    parser.feed(html)
    return clean_title(parser.text() or "Без названия"), parser.href or "#"


def parse_lesson_item(html: str) -> tuple[str, str]:
    parser = _FragmentParser("div", "link title")
    parser.feed(html)
    return clean_title(parser.text() or "Без названия"), parser.href or "#"


def _canonical_content_url(base_url: str, candidate: str, kind: str) -> str | None:
    decoded = unescape(candidate).replace("\\/", "/").strip()
    parsed = urlsplit(urljoin(base_url, decoded))
    base = urlsplit(base_url)
    if not parsed.netloc or parsed.netloc.casefold() != base.netloc.casefold():
        return None

    identifier: str | None = None
    path_match = re.search(
        rf"/(?:pl/)?teach/control/{kind}/view/id/(\d+)",
        parsed.path,
        flags=re.IGNORECASE,
    )
    if path_match:
        identifier = path_match.group(1)
    elif re.search(
        rf"/(?:pl/)?teach/control/{kind}/view/?$",
        parsed.path,
        flags=re.IGNORECASE,
    ):
        values = parse_qs(parsed.query).get("id", [])
        if values and values[0].isdigit():
            identifier = values[0]

    if identifier is None:
        return None
    return urlunsplit(
        (
            parsed.scheme or base.scheme,
            parsed.netloc,
            f"/teach/control/{kind}/view/id/{identifier}",
            "",
            "",
        )
    )


def normalize_stream_url(base_url: str, candidate: str) -> str | None:
    return _canonical_content_url(base_url, candidate, "stream")


def normalize_lesson_url(base_url: str, candidate: str) -> str | None:
    return _canonical_content_url(base_url, candidate, "lesson")


def extract_stream_urls(html: str, base_url: str) -> list[str]:
    normalized_html = unescape(html).replace("\\/", "/")
    result: list[str] = []
    seen: set[str] = set()
    for match in _STREAM_REFERENCE_RE.finditer(normalized_html):
        url = normalize_stream_url(base_url, match.group(0))
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


async def _is_authentication_required(page: Page) -> bool:
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    return "login" in page.url.lower() or "required=true" in page.url.lower()


class GetCourseDiscoverer:
    def __init__(
        self,
        browser_factory: PlaywrightBrowserFactory,
        video_probe: GetCourseVideoProbe | None = None,
    ) -> None:
        self._browsers = browser_factory
        self._video_probe = video_probe or GetCourseVideoProbe()

    async def discover(
        self,
        url: str,
        *,
        on_auth_required: AuthRequiredCallback | None = None,
        on_course_discovered: CourseDiscoveredCallback | None = None,
        on_video_check: VideoCheckCallback | None = None,
    ) -> list[Course]:
        async with async_playwright() as playwright:
            await self._ensure_authenticated(playwright, url, on_auth_required)
            browser = await self._browsers.launch(playwright, headless=True)
            try:
                page = browser.pages[0] if browser.pages else await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                courses = await self._parse_page(page, url)
                courses = await self._video_probe.filter_courses(
                    browser,
                    courses,
                    on_video_check=on_video_check,
                )
                if on_course_discovered:
                    for course in courses:
                        await on_course_discovered(course.title, len(course.lessons))
                return courses
            finally:
                await browser.close()

    async def _ensure_authenticated(
        self,
        playwright: Playwright,
        url: str,
        callback: AuthRequiredCallback | None,
    ) -> None:
        browser = await self._browsers.launch(playwright, headless=True)
        try:
            page = browser.pages[0] if browser.pages else await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            needs_auth = await _is_authentication_required(page)
        finally:
            await browser.close()

        if not needs_auth:
            return

        browser = await self._browsers.launch(playwright, headless=False)
        try:
            login_page = browser.pages[0] if browser.pages else await browser.new_page()
            await login_page.goto(url, wait_until="domcontentloaded")
            message = "Войдите в аккаунт в открывшемся браузере"
            while True:
                if callback:
                    await callback(message)
                else:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, input)

                check_page = await browser.new_page()
                try:
                    await check_page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                    if not await _is_authentication_required(check_page):
                        return
                    message = "Вход ещё не выполнен. Войдите и повторите проверку"
                finally:
                    await check_page.close()
        finally:
            await browser.close()

    async def _parse_page(
        self,
        page: Page,
        playlist_url: str,
    ) -> list[Course]:
        current_url = page.url or playlist_url
        direct_stream = normalize_stream_url(current_url, current_url)
        if direct_stream:
            seeds = [_StreamLink(direct_stream)]
        else:
            seeds = await self._extract_stream_links(page, current_url)

        visited_streams: set[str] = set()
        seen_lessons: set[str] = set()
        result: list[Course] = []
        for seed in seeds:
            result.extend(
                await self._crawl_stream(
                    page,
                    seed,
                    parent_titles=(),
                    visited_streams=visited_streams,
                    seen_lessons=seen_lessons,
                )
            )
        return result

    async def _crawl_stream(
        self,
        page: Page,
        stream: _StreamLink,
        *,
        parent_titles: tuple[str, ...],
        visited_streams: set[str],
        seen_lessons: set[str],
    ) -> list[Course]:
        if stream.url in visited_streams:
            return []
        if len(visited_streams) >= MAX_STREAMS:
            raise ExternalServiceError(
                f"Обход остановлен: найдено больше {MAX_STREAMS} вложенных курсов"
            )
        visited_streams.add(stream.url)

        await page.goto(stream.url, wait_until="domcontentloaded", timeout=30_000)
        if await _is_authentication_required(page):
            raise ExternalServiceError("Сессия GetCourse завершилась во время обхода курсов")

        title = await self._read_stream_title(page, stream)
        title_path = self._append_title(parent_titles, title)
        course_title = " → ".join(title_path)

        direct_lessons = await self._read_lessons(page, page.url)
        lessons: list[Lesson] = []
        for lesson in direct_lessons:
            if lesson.url not in seen_lessons:
                seen_lessons.add(lesson.url)
                lessons.append(lesson)

        result: list[Course] = []
        if lessons:
            result.append(Course(title=course_title, lessons=tuple(lessons)))

        children = await self._extract_stream_links(page, page.url)
        for child in children:
            result.extend(
                await self._crawl_stream(
                    page,
                    child,
                    parent_titles=title_path,
                    visited_streams=visited_streams,
                    seen_lessons=seen_lessons,
                )
            )
        return result

    @staticmethod
    async def _extract_stream_links(page: Page, base_url: str) -> list[_StreamLink]:
        ordered: list[_StreamLink] = []
        indexes: dict[str, int] = {}

        rows = await page.query_selector_all("tr.training-row")
        for row in rows:
            title, href = parse_course_row(await row.inner_html())
            url = normalize_stream_url(base_url, href)
            if not url or url in indexes:
                continue
            hint = title if title != "Без названия" else None
            indexes[url] = len(ordered)
            ordered.append(_StreamLink(url=url, title=hint))

        for url in extract_stream_urls(await page.content(), base_url):
            if url not in indexes:
                indexes[url] = len(ordered)
                ordered.append(_StreamLink(url=url))
        return ordered

    @staticmethod
    async def _read_stream_title(page: Page, stream: _StreamLink) -> str:
        for selector in ("h1", ".training-title", ".page-header"):
            element = await page.query_selector(selector)
            if element:
                title = clean_title(await element.inner_text())
                if title:
                    return title
        if stream.title:
            return stream.title
        identifier = stream.url.rstrip("/").rsplit("/", maxsplit=1)[-1]
        return f"Курс {identifier}"

    @staticmethod
    def _append_title(parent_titles: tuple[str, ...], title: str) -> tuple[str, ...]:
        if parent_titles and parent_titles[-1].casefold() == title.casefold():
            return parent_titles
        return (*parent_titles, title)

    @staticmethod
    async def _read_lessons(page: Page, base_url: str) -> list[Lesson]:
        elements = await page.query_selector_all("ul.lesson-list li")
        lessons: list[Lesson] = []
        seen: set[str] = set()
        for element in elements:
            title, href = parse_lesson_item(await element.inner_html())
            url = normalize_lesson_url(base_url, href)
            if not url or title == "Без названия" or url in seen:
                continue
            seen.add(url)
            lessons.append(Lesson(title=title, url=url))
        return lessons
