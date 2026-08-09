import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError

from app.scripts import live_browser


class _FakePage:
    def __init__(self, goto_error: PlaywrightError | None = None) -> None:
        self.goto_error = goto_error
        self.goto_calls: list[tuple[str, str]] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        if self.goto_error:
            raise self.goto_error


class _FakeBrowser:
    def __init__(
        self,
        pages: list[_FakePage] | None = None,
        wait_error: BaseException | None = None,
    ) -> None:
        self.pages = pages or []
        self.created_page = _FakePage()
        self.wait_error = wait_error
        self.new_page_calls = 0
        self.wait_calls: list[tuple[str, int]] = []
        self.close_calls = 0

    async def new_page(self) -> _FakePage:
        self.new_page_calls += 1
        return self.created_page

    async def wait_for_event(self, event: str, *, timeout: int) -> None:
        self.wait_calls.append((event, timeout))
        if self.wait_error:
            raise self.wait_error

    async def close(self) -> None:
        self.close_calls += 1


def test_open_live_browser_uses_existing_page_and_url(monkeypatch):
    page = _FakePage()
    browser = _FakeBrowser([page])
    launch_calls = []

    async def fake_launch(playwright, *, headless):
        launch_calls.append((playwright, headless))
        return browser

    monkeypatch.setattr(live_browser, "launch_browser", fake_launch)
    playwright = object()

    asyncio.run(live_browser.open_live_browser(playwright, "https://example.com/course"))

    assert launch_calls == [(playwright, False)]
    assert page.goto_calls == [("https://example.com/course", "domcontentloaded")]
    assert browser.new_page_calls == 0
    assert browser.wait_calls == [("close", 0)]
    assert browser.close_calls == 1


def test_open_live_browser_creates_blank_page(monkeypatch):
    browser = _FakeBrowser()

    async def fake_launch(playwright, *, headless):
        return browser

    monkeypatch.setattr(live_browser, "launch_browser", fake_launch)

    asyncio.run(live_browser.open_live_browser(object()))

    assert browser.new_page_calls == 1
    assert browser.created_page.goto_calls == [("about:blank", "domcontentloaded")]
    assert browser.wait_calls == [("close", 0)]
    assert browser.close_calls == 1


def test_open_live_browser_keeps_running_after_navigation_error(monkeypatch, capsys):
    page = _FakePage(PlaywrightError("navigation failed"))
    browser = _FakeBrowser([page])

    async def fake_launch(playwright, *, headless):
        return browser

    monkeypatch.setattr(live_browser, "launch_browser", fake_launch)

    asyncio.run(live_browser.open_live_browser(object(), "https://example.com/course"))

    assert browser.wait_calls == [("close", 0)]
    assert browser.close_calls == 1
    assert "navigation failed" in capsys.readouterr().err


def test_open_live_browser_explains_profile_lock(monkeypatch):
    async def fake_launch(playwright, *, headless):
        raise PlaywrightError("profile is already in use")

    monkeypatch.setattr(live_browser, "launch_browser", fake_launch)

    with pytest.raises(live_browser.LiveBrowserLaunchError) as error:
        asyncio.run(live_browser.open_live_browser(object()))

    message = str(error.value)
    assert "session_data" in message
    assert "Закройте основное приложение" in message


def test_open_live_browser_closes_context_when_interrupted(monkeypatch):
    browser = _FakeBrowser(wait_error=asyncio.CancelledError())

    async def fake_launch(playwright, *, headless):
        return browser

    monkeypatch.setattr(live_browser, "launch_browser", fake_launch)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(live_browser.open_live_browser(object()))

    assert browser.close_calls == 1


def test_main_returns_error_for_launch_failure(monkeypatch, capsys):
    async def fake_run(url):
        raise live_browser.LiveBrowserLaunchError("profile is busy")

    monkeypatch.setattr(live_browser, "run_live_browser", fake_run)

    assert live_browser.main(["https://example.com"]) == 1
    assert "profile is busy" in capsys.readouterr().err
