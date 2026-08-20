import asyncio
from types import SimpleNamespace

import flet as ft

from getcourse_downloader.presentation.flet.app import App


class _Window:
    def __init__(self) -> None:
        self.prevent_close = False
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Page:
    def __init__(self) -> None:
        self.window = _Window()


class _Screen:
    def __init__(self) -> None:
        self.disposed = False
        self.shutdown_timeout = None

    def dispose(self) -> None:
        self.disposed = True

    def shutdown(self, timeout: float) -> None:
        self.shutdown_timeout = timeout


def test_window_close_cancels_and_waits_for_active_screen():
    page = _Page()
    app = App(page, container=object())  # type: ignore[arg-type]
    screen = _Screen()
    app._screen = screen

    asyncio.run(app._on_window_event(SimpleNamespace(type=ft.WindowEventType.CLOSE)))

    assert screen.disposed
    assert screen.shutdown_timeout == 6.0
    assert page.window.prevent_close is False
    assert page.window.closed
