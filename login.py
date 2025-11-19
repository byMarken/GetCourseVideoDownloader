"""Вспомогательные функции для проверки авторизации пользователя."""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import Page, async_playwright

from utils_config import get_env_config

LOGIN_REDIRECT_URL = "https://school.beilbei.ru/cms/system/login?required=true"


async def ensure_login_active(page: Page) -> bool:
    """Проверяет авторизацию и инициирует ручной вход при необходимости."""

    current_url = page.url.strip()

    if current_url.startswith(LOGIN_REDIRECT_URL):
        cfg = get_env_config()
        is_headless = cfg["headless"]

        print("❌ Авторизация недействительна — вы попали на страницу логина.")

        if is_headless:
            print("⚙️ Запущено в headless-режиме — требуется ручной вход.")
            print("   🔑 Сейчас откроется окно браузера для авторизации.")
            print("   ⏳ После входа перезапустите программу вручную.")

            try:
                await page.context.close()
            except Exception:  # noqa: BLE001
                pass

            async with async_playwright() as playwright:
                browser = await playwright.firefox.launch_persistent_context(
                    "session_data",
                    headless=False,
                    args=["--mute-audio"],
                )
                visible_page = await browser.new_page()
                await visible_page.goto(LOGIN_REDIRECT_URL)
                print("🌐 Браузер открыт. Войдите вручную в течение 5 минут.")

                try:
                    await visible_page.wait_for_function(
                        "() => !window.location.href.includes('login?required=true')",
                        timeout=300_000,
                    )
                    print("✅ Авторизация успешно выполнена.")
                except asyncio.TimeoutError:
                    print(
                        "⚠️ Время ожидания истекло (5 минут). Авторизация не выполнена."
                    )
                finally:
                    await browser.close()
                    print("\n🔁 Перезапустите программу после успешного входа.")
                    sys.exit(0)

        else:
            print("🔓 Браузер видимый — ожидаем авторизацию пользователя.")
            try:
                await page.wait_for_function(
                    "() => !window.location.href.includes('login?required=true')",
                    timeout=300_000,
                )
                print("✅ Авторизация выполнена, продолжаем работу.")
                return True
            except asyncio.TimeoutError:
                print("⚠️ Истекло время ожидания (5 минут). Авторизация не выполнена.")
                return False

    if "teach/control/" in current_url or "stream/view" in current_url:
        print("✅ Авторизация активна.")
        return True

    return True
