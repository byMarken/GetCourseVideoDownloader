import asyncio
from typing import Any

import pytest

from getcourse_downloader.domain.errors import ExternalServiceError
from getcourse_downloader.domain.events import VideoCheckEvent, VideoCheckStatus
from getcourse_downloader.domain.models import Course, Lesson
from getcourse_downloader.infrastructure.getcourse.video_probe import (
    GetCourseVideoProbe,
    is_master_playlist_response,
)


class _FakeResponse:
    def __init__(self, url: str, *, ok: bool = True) -> None:
        self.url = url
        self.ok = ok


class _FakePage:
    def __init__(
        self,
        video_urls: set[str],
        player_urls: set[str],
        auth_urls: set[str],
    ) -> None:
        self._video_urls = video_urls
        self._player_urls = player_urls
        self._auth_urls = auth_urls
        self._response_handlers: list[Any] = []
        self.url = "about:blank"
        self.closed = False

    def on(self, event: str, handler: Any) -> None:
        if event == "response":
            self._response_handlers.append(handler)

    async def goto(self, url: str, **_: object) -> None:
        self.url = "https://school.example/login" if url in self._auth_urls else url
        if url in self._video_urls:
            response = _FakeResponse("https://rutube.example/api/playlist/master/123.m3u8")
            for handler in self._response_handlers:
                handler(response)

    async def close(self) -> None:
        self.closed = True

    async def query_selector(self, _: str) -> object | None:
        return object() if self.url in self._player_urls else None


class _FakeBrowser:
    def __init__(
        self,
        *,
        video_urls: set[str],
        player_urls: set[str] | None = None,
        auth_urls: set[str] | None = None,
    ) -> None:
        self._video_urls = video_urls
        self._player_urls = player_urls or set()
        self._auth_urls = auth_urls or set()
        self.pages: list[_FakePage] = []

    async def new_page(self) -> _FakePage:
        page = _FakePage(self._video_urls, self._player_urls, self._auth_urls)
        self.pages.append(page)
        return page


def test_master_playlist_response_requires_successful_supported_url():
    supported: Any = _FakeResponse("https://rutube.example/api/playlist/master/123.m3u8")
    failed: Any = _FakeResponse(
        "https://rutube.example/api/playlist/master/123.m3u8",
        ok=False,
    )
    unrelated: Any = _FakeResponse("https://rutube.example/poster.jpg")
    rutube: Any = _FakeResponse("https://bl.rutube.ru/route/video/master.m3u8?token=abc")

    assert is_master_playlist_response(supported)
    assert is_master_playlist_response(rutube)
    assert not is_master_playlist_response(failed)
    assert not is_master_playlist_response(unrelated)


def test_filter_courses_keeps_only_lessons_with_confirmed_video():
    playlist_url = "https://school.example/lesson/playlist"
    player_url = "https://school.example/lesson/player"
    text_url = "https://school.example/lesson/text"
    paid_url = "https://school.example/lesson/paid"
    courses = [
        Course(
            title="Курс с видео",
            lessons=(
                Lesson(title="Видео с потоком", url=playlist_url),
                Lesson(title="Видео с плеером", url=player_url),
                Lesson(title="Текст", url=text_url),
            ),
        ),
        Course(
            title="Закрытый курс",
            lessons=(Lesson(title="Купить доступ", url=paid_url),),
        ),
    ]
    browser: Any = _FakeBrowser(
        video_urls={playlist_url},
        player_urls={player_url},
    )
    probe = GetCourseVideoProbe(concurrency=2, response_timeout=0)
    events: list[VideoCheckEvent] = []

    async def on_video_check(event: VideoCheckEvent) -> None:
        events.append(event)

    filtered = asyncio.run(probe.filter_courses(browser, courses, on_video_check=on_video_check))

    assert filtered == [
        Course(
            title="Курс с видео",
            lessons=(
                Lesson(title="Видео с потоком", url=playlist_url),
                Lesson(title="Видео с плеером", url=player_url),
            ),
        )
    ]
    assert len(browser.pages) == 4
    assert all(page.closed for page in browser.pages)
    checking = [event for event in events if event.status is VideoCheckStatus.CHECKING]
    completed = [event for event in events if event.status is not VideoCheckStatus.CHECKING]
    assert {event.lesson_url for event in checking} == {
        playlist_url,
        player_url,
        text_url,
        paid_url,
    }
    assert sorted(event.checked for event in completed) == [1, 2, 3, 4]
    assert {event.lesson_url for event in completed if event.status is VideoCheckStatus.VIDEO} == {
        playlist_url,
        player_url,
    }
    assert events[-1].checked == 4
    assert events[-1].video_count == 2


def test_filter_courses_reports_expired_authentication():
    lesson_url = "https://school.example/lesson/1"
    courses = [
        Course(
            title="Курс",
            lessons=(Lesson(title="Урок", url=lesson_url),),
        )
    ]
    browser: Any = _FakeBrowser(video_urls=set(), auth_urls={lesson_url})
    probe = GetCourseVideoProbe(response_timeout=0)

    with pytest.raises(ExternalServiceError, match="Сессия GetCourse завершилась"):
        asyncio.run(probe.filter_courses(browser, courses))

    assert browser.pages[0].closed
