from __future__ import annotations

import os

from playwright.async_api import BrowserContext, Playwright

from app.utils.paths import resources_dir, session_data_dir

USER_DATA_DIR = str(session_data_dir())


def _configure_playwright_env() -> None:
    browsers = resources_dir() / "ms-playwright"
    if browsers.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))


_configure_playwright_env()


async def launch_browser(
    playwright: Playwright,
    *,
    headless: bool,
) -> BrowserContext:
    return await playwright.firefox.launch_persistent_context(
        USER_DATA_DIR,
        headless=headless,
    )
