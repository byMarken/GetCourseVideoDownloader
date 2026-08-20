from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from getcourse_downloader.application.ports.discovery import (
    AuthRequiredCallback,
    CourseDiscoveredCallback,
    CourseDiscoveryUpdate,
)
from getcourse_downloader.domain.errors import ExternalServiceError
from getcourse_downloader.domain.models import Course, Lesson
from getcourse_downloader.infrastructure.browser.playwright import PlaywrightBrowserFactory

MAX_STREAMS = 500
DISCOVERY_CONCURRENCY = 4

_STREAM_REFERENCE_RE = re.compile(
    r"(?:(?:https?:)?//[^\"'<>\s\\]+)?/(?:pl/)?teach/control/stream/"
    r"(?:view/id/\d+|view\?[^\"'<>\s\\]*\bid=\d+[^\"'<>\s\\]*)",
    flags=re.IGNORECASE,
)

_LESSON_REFERENCE_RE = re.compile(
    r"(?:(?:https?:)?//[^\"'<>\s\\]+)?/(?:pl/)?teach/control/lesson/"
    r"(?:view/id/\d+|view\?[^\"'<>\s\\]*\bid=\d+[^\"'<>\s\\]*)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _StreamLink:
    url: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class _StreamSnapshot:
    title: str
    lessons: tuple[Lesson, ...]
    children: tuple[_StreamLink, ...]


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


def extract_lesson_urls(html: str, base_url: str) -> list[str]:
    normalized_html = unescape(html).replace("\\/", "/")
    result: list[str] = []
    seen: set[str] = set()
    for match in _LESSON_REFERENCE_RE.finditer(normalized_html):
        url = normalize_lesson_url(base_url, match.group(0))
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def _is_stream_landing_url(url: str) -> bool:
    path = urlsplit(url).path.rstrip("/")
    return bool(
        re.fullmatch(
            r"/(?:pl/)?teach/control(?:/stream(?:/index)?)?",
            path,
            flags=re.IGNORECASE,
        )
    )


async def _is_authentication_required(page: Page) -> bool:
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    return "login" in page.url.lower() or "required=true" in page.url.lower()


class GetCourseDiscoverer:
    def __init__(
        self,
        browser_factory: PlaywrightBrowserFactory,
        *,
        concurrency: int = DISCOVERY_CONCURRENCY,
    ) -> None:
        if concurrency < 1 or concurrency > DISCOVERY_CONCURRENCY:
            raise ValueError(f"concurrency must be between 1 and {DISCOVERY_CONCURRENCY}")
        self._browsers = browser_factory
        self._concurrency = concurrency

    async def discover(
        self,
        url: str,
        *,
        on_auth_required: AuthRequiredCallback | None = None,
        on_course_discovered: CourseDiscoveredCallback | None = None,
    ) -> list[Course]:
        async with async_playwright() as playwright:
            browser = await self._browsers.launch(playwright, headless=True)
            try:
                page = browser.pages[0] if browser.pages else await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                if await _is_authentication_required(page):
                    await browser.close()
                    await self._authenticate_interactive(playwright, url, on_auth_required)
                    browser = await self._browsers.launch(playwright, headless=True)
                    page = browser.pages[0] if browser.pages else await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded")
                return await self._parse_page(
                    browser,
                    page,
                    url,
                    on_course_discovered=on_course_discovered,
                )
            finally:
                await browser.close()

    async def _authenticate_interactive(
        self,
        playwright: Playwright,
        url: str,
        callback: AuthRequiredCallback | None,
    ) -> None:
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
        browser: BrowserContext,
        page: Page,
        playlist_url: str,
        *,
        on_course_discovered: CourseDiscoveredCallback | None = None,
    ) -> list[Course]:
        current_url = page.url or playlist_url
        direct_stream = normalize_stream_url(current_url, current_url)
        initial_graph: dict[str, _StreamSnapshot] = {}
        try:
            if direct_stream:
                seeds = [_StreamLink(direct_stream)]
                snapshot = await self._read_loaded_stream(page, seeds[0])
                initial_graph[direct_stream] = snapshot
                if on_course_discovered:
                    await on_course_discovered(
                        CourseDiscoveryUpdate(
                            direct_stream,
                            snapshot.title,
                            self._resolved_snapshot_count(snapshot),
                        )
                    )
                    for child in snapshot.children:
                        await on_course_discovered(self._discovery_update(child))
            else:
                seeds = await self._extract_stream_links(
                    page,
                    current_url,
                    allow_fallback=_is_stream_landing_url(current_url),
                )
                if on_course_discovered:
                    for seed in seeds:
                        await on_course_discovered(self._discovery_update(seed))

            semaphore = asyncio.Semaphore(self._concurrency)
            callback_lock = asyncio.Lock()
            graph = await self._fetch_stream_graph(
                browser,
                seeds,
                semaphore=semaphore,
                callback_lock=callback_lock,
                on_course_discovered=on_course_discovered,
                initial_graph=initial_graph,
            )
            claimed: set[str] = set()
            courses = [self._build_tree(seed, graph, claimed) for seed in seeds]
            return [course for course in courses if course is not None]
        finally:
            with contextlib.suppress(Exception):
                await page.close()

    async def _fetch_stream_graph(
        self,
        browser: BrowserContext,
        seeds: list[_StreamLink],
        *,
        semaphore: asyncio.Semaphore,
        callback_lock: asyncio.Lock,
        on_course_discovered: CourseDiscoveredCallback | None,
        initial_graph: dict[str, _StreamSnapshot],
    ) -> dict[str, _StreamSnapshot]:
        graph = dict(initial_graph)
        reported_counts = {
            stream_url: self._resolved_snapshot_count(snapshot)
            for stream_url, snapshot in graph.items()
        }
        scheduled = set(graph)
        frontier: list[_StreamLink] = []
        for seed in seeds:
            snapshot = graph.get(seed.url)
            if snapshot is None:
                self._extend_frontier(frontier, [seed], scheduled)
            else:
                self._extend_frontier(frontier, snapshot.children, scheduled)

        while frontier:
            snapshots = await asyncio.gather(
                *(
                    self._fetch_stream(
                        browser,
                        stream,
                        semaphore=semaphore,
                        callback_lock=callback_lock,
                        on_course_discovered=on_course_discovered,
                    )
                    for stream in frontier
                )
            )
            next_frontier: list[_StreamLink] = []
            for stream, snapshot in zip(frontier, snapshots, strict=True):
                graph[stream.url] = snapshot
                reported_counts[stream.url] = self._resolved_snapshot_count(snapshot)
                self._extend_frontier(next_frontier, snapshot.children, scheduled)
            if on_course_discovered:
                claimed: set[str] = set()
                partial_courses = [self._build_tree(seed, graph, claimed) for seed in seeds]
                async with callback_lock:
                    for course in self._walk_courses(
                        course for course in partial_courses if course is not None
                    ):
                        if not self._is_subtree_loaded(course.url, graph):
                            continue
                        if reported_counts.get(course.url) == course.lesson_count:
                            continue
                        reported_counts[course.url] = course.lesson_count
                        await on_course_discovered(
                            CourseDiscoveryUpdate(
                                course.url,
                                course.title,
                                course.lesson_count,
                            )
                        )
            frontier = next_frontier
        return graph

    @classmethod
    def _walk_courses(cls, courses: Iterable[Course]) -> Iterable[Course]:
        for course in courses:
            yield course
            yield from cls._walk_courses(course.children)

    @staticmethod
    def _resolved_snapshot_count(snapshot: _StreamSnapshot) -> int | None:
        if snapshot.children:
            return None
        return len(snapshot.lessons)

    @classmethod
    def _is_subtree_loaded(
        cls,
        stream_url: str,
        graph: dict[str, _StreamSnapshot],
        visiting: set[str] | None = None,
    ) -> bool:
        snapshot = graph.get(stream_url)
        if snapshot is None:
            return False
        path = set() if visiting is None else visiting
        if stream_url in path:
            return True
        path.add(stream_url)
        try:
            return all(
                cls._is_subtree_loaded(child.url, graph, path) for child in snapshot.children
            )
        finally:
            path.remove(stream_url)

    @staticmethod
    def _extend_frontier(
        frontier: list[_StreamLink],
        candidates: list[_StreamLink] | tuple[_StreamLink, ...],
        scheduled: set[str],
    ) -> None:
        for candidate in candidates:
            if candidate.url in scheduled:
                continue
            if len(scheduled) >= MAX_STREAMS:
                raise ExternalServiceError(
                    f"Обход остановлен: найдено больше {MAX_STREAMS} вложенных курсов"
                )
            scheduled.add(candidate.url)
            frontier.append(candidate)

    async def _fetch_stream(
        self,
        browser: BrowserContext,
        stream: _StreamLink,
        *,
        semaphore: asyncio.Semaphore,
        callback_lock: asyncio.Lock,
        on_course_discovered: CourseDiscoveredCallback | None,
    ) -> _StreamSnapshot:
        async with semaphore:
            page = await browser.new_page()
            try:
                await page.goto(stream.url, wait_until="domcontentloaded", timeout=30_000)
                snapshot = await self._read_loaded_stream(page, stream)
            finally:
                with contextlib.suppress(Exception):
                    await page.close()

        if on_course_discovered:
            async with callback_lock:
                await on_course_discovered(
                    CourseDiscoveryUpdate(
                        stream.url,
                        snapshot.title,
                        self._resolved_snapshot_count(snapshot),
                    )
                )
                for child in snapshot.children:
                    await on_course_discovered(self._discovery_update(child))

        return snapshot

    @staticmethod
    def _discovery_update(stream: _StreamLink) -> CourseDiscoveryUpdate:
        fallback = stream.url.rstrip("/").rsplit("/", maxsplit=1)[-1]
        return CourseDiscoveryUpdate(stream.url, stream.title or f"Курс {fallback}")

    async def _read_loaded_stream(self, page: Page, stream: _StreamLink) -> _StreamSnapshot:
        if await _is_authentication_required(page):
            raise ExternalServiceError("Сессия GetCourse завершилась во время обхода курсов")
        title = await self._read_stream_title(page, stream)
        lessons = tuple(await self._read_lessons(page, page.url))
        children = tuple(
            await self._extract_stream_links(
                page,
                page.url,
                allow_fallback=False,
            )
        )
        return _StreamSnapshot(title=title, lessons=lessons, children=children)

    @classmethod
    def _build_tree(
        cls,
        stream: _StreamLink,
        graph: dict[str, _StreamSnapshot],
        claimed: set[str],
    ) -> Course | None:
        if stream.url in claimed:
            return None
        snapshot = graph.get(stream.url)
        if snapshot is None:
            return None
        claimed.add(stream.url)
        children = tuple(
            child_course
            for child in snapshot.children
            if (child_course := cls._build_tree(child, graph, claimed)) is not None
        )
        return Course(
            title=snapshot.title,
            lessons=snapshot.lessons,
            url=stream.url,
            children=children,
        )

    @staticmethod
    async def _link_details(element, parser) -> tuple[str, str | None]:
        title, href = parser(await element.inner_html())
        if href != "#":
            return title, href
        href = await element.get_attribute("href")
        if href:
            return clean_title(await element.inner_text()) or "Без названия", href
        return title, None

    @classmethod
    async def _extract_stream_links(
        cls,
        page: Page,
        base_url: str,
        *,
        allow_fallback: bool,
    ) -> list[_StreamLink]:
        ordered: list[_StreamLink] = []
        indexes: dict[str, int] = {}

        rows = await page.query_selector_all("tr.training-row")
        rows.extend(await page.query_selector_all(".training-item"))
        rows.extend(await page.query_selector_all("a[href*='/teach/control/stream/']"))
        for row in rows:
            title, href = await cls._link_details(row, parse_course_row)
            url = normalize_stream_url(base_url, href) if href else None
            if not url or url in indexes:
                continue
            hint = title if title != "Без названия" else None
            indexes[url] = len(ordered)
            ordered.append(_StreamLink(url=url, title=hint))

        if allow_fallback and not ordered:
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

    @classmethod
    async def _read_lessons(cls, page: Page, base_url: str) -> list[Lesson]:
        elements = await page.query_selector_all("ul.lesson-list li")
        elements.extend(await page.query_selector_all("a[href*='/teach/control/lesson/']"))
        lessons: list[Lesson] = []
        seen: set[str] = set()
        for element in elements:
            title, href = await cls._link_details(element, parse_lesson_item)
            url = normalize_lesson_url(base_url, href) if href else None
            if not url or url in seen:
                continue
            seen.add(url)
            identifier = url.rstrip("/").rsplit("/", maxsplit=1)[-1]
            lessons.append(
                Lesson(
                    title=title if title != "Без названия" else f"Урок {identifier}",
                    url=url,
                )
            )
        if lessons:
            return lessons
        for url in extract_lesson_urls(await page.content(), base_url):
            identifier = url.rstrip("/").rsplit("/", maxsplit=1)[-1]
            lessons.append(Lesson(title=f"Урок {identifier}", url=url))
        return lessons
