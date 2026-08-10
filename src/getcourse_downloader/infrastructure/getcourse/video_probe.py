from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from enum import Enum, auto

from playwright.async_api import BrowserContext, Page, Response
from playwright.async_api import Error as PlaywrightError

from getcourse_downloader.application.ports.discovery import VideoCheckCallback
from getcourse_downloader.domain.errors import ExternalServiceError
from getcourse_downloader.domain.events import VideoCheckEvent, VideoCheckStatus
from getcourse_downloader.domain.models import Course, Lesson
from getcourse_downloader.infrastructure.getcourse.video_signals import (
    VIDEO_PLAYER_SELECTOR,
    is_hls_playlist_url,
)

PROBE_CONCURRENCY = 4
PROBE_NAVIGATION_TIMEOUT = 30_000
PROBE_RESPONSE_TIMEOUT = 8.0


class _ProbeResult(Enum):
    VIDEO = auto()
    NO_VIDEO = auto()
    AUTH_REQUIRED = auto()


def is_master_playlist_response(response: Response) -> bool:
    return response.ok and is_hls_playlist_url(response.url)


class GetCourseVideoProbe:
    def __init__(
        self,
        *,
        concurrency: int = PROBE_CONCURRENCY,
        response_timeout: float = PROBE_RESPONSE_TIMEOUT,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if response_timeout < 0:
            raise ValueError("response_timeout cannot be negative")
        self._concurrency = concurrency
        self._response_timeout = response_timeout

    async def filter_courses(
        self,
        browser: BrowserContext,
        courses: Sequence[Course],
        *,
        on_video_check: VideoCheckCallback | None = None,
    ) -> list[Course]:
        lessons_by_url = {lesson.url: lesson for course in courses for lesson in course.lessons}
        unique_lessons = list(lessons_by_url.values())
        semaphore = asyncio.Semaphore(self._concurrency)
        notification_lock = asyncio.Lock()
        checked = 0
        video_count = 0

        async def probe(lesson: Lesson) -> _ProbeResult:
            nonlocal checked, video_count
            async with semaphore:
                if on_video_check:
                    async with notification_lock:
                        await on_video_check(
                            VideoCheckEvent(
                                lesson_url=lesson.url,
                                lesson_title=lesson.title,
                                status=VideoCheckStatus.CHECKING,
                                checked=checked,
                                total=len(unique_lessons),
                                video_count=video_count,
                            )
                        )

                result = await self._probe_lesson(browser, lesson.url)
                if result is _ProbeResult.AUTH_REQUIRED:
                    return result

                async with notification_lock:
                    checked += 1
                    if result is _ProbeResult.VIDEO:
                        video_count += 1
                    if on_video_check:
                        await on_video_check(
                            VideoCheckEvent(
                                lesson_url=lesson.url,
                                lesson_title=lesson.title,
                                status=(
                                    VideoCheckStatus.VIDEO
                                    if result is _ProbeResult.VIDEO
                                    else VideoCheckStatus.NO_VIDEO
                                ),
                                checked=checked,
                                total=len(unique_lessons),
                                video_count=video_count,
                            )
                        )
                return result

        results = await asyncio.gather(*(probe(lesson) for lesson in unique_lessons))

        if _ProbeResult.AUTH_REQUIRED in results:
            raise ExternalServiceError("Сессия GetCourse завершилась во время проверки видео")

        has_video = {
            lesson.url: result is _ProbeResult.VIDEO
            for lesson, result in zip(unique_lessons, results, strict=True)
        }
        filtered: list[Course] = []
        for course in courses:
            course_lessons = tuple(lesson for lesson in course.lessons if has_video[lesson.url])
            if course_lessons:
                filtered.append(Course(title=course.title, lessons=course_lessons))
        return filtered

    async def _probe_lesson(
        self,
        browser: BrowserContext,
        lesson_url: str,
    ) -> _ProbeResult:
        page = await browser.new_page()
        playlist_received = asyncio.Event()

        def on_response(response: Response) -> None:
            if is_master_playlist_response(response):
                playlist_received.set()

        page.on("response", on_response)
        try:
            try:
                await page.goto(
                    lesson_url,
                    wait_until="commit",
                    timeout=PROBE_NAVIGATION_TIMEOUT,
                )
            except PlaywrightError:
                return _ProbeResult.NO_VIDEO

            if self._authentication_required(page):
                return _ProbeResult.AUTH_REQUIRED
            if playlist_received.is_set() or await self._has_video_player(page):
                return _ProbeResult.VIDEO

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    playlist_received.wait(),
                    timeout=self._response_timeout,
                )
            if playlist_received.is_set() or await self._has_video_player(page):
                return _ProbeResult.VIDEO
            return _ProbeResult.NO_VIDEO
        finally:
            with contextlib.suppress(PlaywrightError):
                await page.close()

    @staticmethod
    def _authentication_required(page: Page) -> bool:
        current_url = page.url.casefold()
        return "login" in current_url or "required=true" in current_url

    @staticmethod
    async def _has_video_player(page: Page) -> bool:
        with contextlib.suppress(PlaywrightError):
            return await page.query_selector(VIDEO_PLAYER_SELECTOR) is not None
        return False
