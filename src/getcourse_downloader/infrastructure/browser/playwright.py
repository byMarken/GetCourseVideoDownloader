from __future__ import annotations

import os

from playwright.async_api import BrowserContext, Playwright

from getcourse_downloader.infrastructure.platform.paths import AppPaths


class PlaywrightBrowserFactory:
    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths
        self._paths.ensure_runtime_directories()
        bundled_browsers = paths.resources / "ms-playwright"
        if bundled_browsers.is_dir():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled_browsers))

    @property
    def profile_path(self) -> str:
        return str(self._paths.session)

    async def launch(self, playwright: Playwright, *, headless: bool) -> BrowserContext:
        return await playwright.firefox.launch_persistent_context(
            self.profile_path,
            headless=headless,
        )
