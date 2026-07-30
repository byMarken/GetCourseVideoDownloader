from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserContext, Playwright

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
USER_DATA_DIR = str(_PROJECT_ROOT / "session_data")


async def launch_browser(
    playwright: Playwright,
    *,
    headless: bool,
) -> BrowserContext:
    """Запустить Firefox с постоянным профилем (persistent context).

    Parameters
    ----------
    playwright:
        Экземпляр Playwright, полученный через async_playwright().
    headless:
        True — браузер без GUI (фоновый режим).
        False — браузер с окном (для ручного входа).

    Returns
    -------
    BrowserContext
        Persistent browser context, привязанный к USER_DATA_DIR.
    """
    return await playwright.firefox.launch_persistent_context(
        USER_DATA_DIR,
        headless=headless,
    )
