import asyncio
from typing import Any, cast

import flet as ft

from getcourse_downloader.domain.events import VideoCheckEvent, VideoCheckStatus
from getcourse_downloader.presentation.flet.screens.start.state import StartViewState
from getcourse_downloader.presentation.flet.screens.start.view import StartScreen
from getcourse_downloader.presentation.flet.theme import Color


class _FakeWindow:
    def __init__(self) -> None:
        self.width = 680
        self.height = 460
        self.centered = False

    async def center(self) -> None:
        self.centered = True


class _FakePage:
    def __init__(self) -> None:
        self.window = _FakeWindow()
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


def _screen() -> StartScreen:
    screen = StartScreen.__new__(StartScreen)
    screen.page = _FakePage()  # type: ignore[assignment]
    screen.state = StartViewState()
    screen._loading_task = None
    screen._dot_task = None
    screen._video_check_list = ft.Column(spacing=5)
    screen._video_check_counter = ft.Text("")
    screen._video_check_rows = {}
    screen.loader = ft.Container(visible=True)
    return screen


def _event(
    url: str,
    title: str,
    status: VideoCheckStatus,
    *,
    checked: int,
    total: int = 2,
    videos: int = 0,
) -> VideoCheckEvent:
    return VideoCheckEvent(
        lesson_url=url,
        lesson_title=title,
        status=status,
        checked=checked,
        total=total,
        video_count=videos,
    )


def test_video_check_overlay_updates_rows_live():
    screen = _screen()
    video_url = "https://school.example/lesson/video"
    text_url = "https://school.example/lesson/text"

    asyncio.run(
        screen._on_video_check(
            _event(video_url, "Видео урок", VideoCheckStatus.CHECKING, checked=0)
        )
    )
    video_status, _, video_label, video_row = screen._video_check_rows[video_url]
    assert isinstance(video_status.content, ft.ProgressRing)
    assert video_label.value == "Проверка..."
    assert video_row.opacity == 1
    assert video_row.offset == ft.Offset(0, 0)
    assert screen._video_check_counter.value == "Проверено 0/2  •  С видео 0"

    asyncio.run(
        screen._on_video_check(
            _event(
                video_url,
                "Видео урок",
                VideoCheckStatus.VIDEO,
                checked=1,
                videos=1,
            )
        )
    )
    assert isinstance(video_status.content, ft.Icon)
    video_icon = cast(Any, video_status.content)
    assert video_icon.icon == ft.Icons.CHECK_CIRCLE_ROUNDED
    assert video_label.value == "Есть видео"
    assert video_label.color == Color.GREEN

    asyncio.run(
        screen._on_video_check(
            _event(text_url, "Текст", VideoCheckStatus.CHECKING, checked=1, videos=1)
        )
    )
    asyncio.run(
        screen._on_video_check(
            _event(text_url, "Текст", VideoCheckStatus.NO_VIDEO, checked=2, videos=1)
        )
    )
    text_status, _, text_label, _ = screen._video_check_rows[text_url]
    assert isinstance(text_status.content, ft.Icon)
    text_icon = cast(Any, text_status.content)
    assert text_icon.icon == ft.Icons.CANCEL_ROUNDED
    assert text_label.value == "Нет видео"
    assert text_label.color == Color.RED
    assert screen._video_check_counter.value == "Проверено 2/2  •  С видео 1"
    page = cast(Any, screen.page)
    assert page.window.width == 680
    assert page.window.height == 460
    assert not page.window.centered
    assert page.updates >= 4
