from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from playwright.async_api import BrowserContext, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from app.utils.browser import launch_browser
from app.utils.paths import session_data_dir


class LiveBrowserLaunchError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Открыть Firefox с сохранённым профилем session_data.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Необязательный URL страницы; без него откроется пустая вкладка.",
    )
    return parser


async def open_live_browser(playwright: Playwright, url: str | None = None) -> None:
    try:
        browser = await launch_browser(playwright, headless=False)
    except PlaywrightError as error:
        raise LiveBrowserLaunchError(
            "Не удалось открыть Firefox с профилем session_data. "
            "Закройте основное приложение и другие экземпляры Firefox, "
            "которые используют эту папку профиля. "
            f"Подробности: {error}"
        ) from error

    try:
        page = browser.pages[0] if browser.pages else await browser.new_page()
        target_url = url or "about:blank"
        try:
            await page.goto(target_url, wait_until="domcontentloaded")
        except PlaywrightError as error:
            print(f"[WARNING] Не удалось открыть {target_url}: {error}", file=sys.stderr)

        print(f"[INFO] Firefox открыт с профилем: {session_data_dir()}")
        print("[INFO] Для инструментов разработчика нажмите F12.")
        print("[INFO] Закройте Firefox, чтобы завершить live_browser.py.")

        await browser.wait_for_event("close", timeout=0)
    finally:
        await _close_browser(browser)


async def _close_browser(browser: BrowserContext) -> None:
    with contextlib.suppress(PlaywrightError):
        await browser.close()


async def run_live_browser(url: str | None = None) -> None:
    async with async_playwright() as playwright:
        await open_live_browser(playwright, url)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(run_live_browser(args.url))
    except LiveBrowserLaunchError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[INFO] Браузер закрыт.")
    except PlaywrightError as error:
        print(f"[ERROR] Работа браузера завершилась с ошибкой: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
