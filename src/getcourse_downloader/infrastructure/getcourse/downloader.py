from __future__ import annotations

import asyncio
import contextlib
import os
import time
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from getcourse_downloader.application.ports.download import EventHandler
from getcourse_downloader.domain.events import DownloadEvent, DownloadEventType
from getcourse_downloader.domain.models import (
    DownloadRequest,
    DownloadSummary,
    SelectedLesson,
)
from getcourse_downloader.infrastructure.browser.playwright import PlaywrightBrowserFactory
from getcourse_downloader.infrastructure.getcourse.video_signals import (
    is_master_playlist_url,
)
from getcourse_downloader.infrastructure.media.hls import (
    HlsDownloader,
    parse_master_playlist,
    select_quality_url,
)
from getcourse_downloader.infrastructure.storage.filenames import sanitize_filename


class _AuthenticationExpired(RuntimeError):
    pass


class PlaywrightDownloadGateway:
    """In-process worker adapter for GetCourse/Rutube downloads."""

    def __init__(self, browsers: PlaywrightBrowserFactory, hls: HlsDownloader) -> None:
        self._browsers = browsers
        self._hls = hls
        self._cancelled = False

    def run(self, request: DownloadRequest, on_event: EventHandler) -> DownloadSummary:
        self._cancelled = False
        return asyncio.run(self._run_async(request, on_event))

    def continue_authentication(self) -> None:
        # Authentication input is supplied through the worker process stdin.
        return None

    def cancel(self) -> None:
        self._cancelled = True

    async def _run_async(self, request: DownloadRequest, emit: EventHandler) -> DownloadSummary:
        failed: list[str] = []
        downloaded = 0

        async with async_playwright() as playwright:
            if request.lessons:
                await self._ensure_authenticated(playwright, request.lessons[0].lesson.url, emit)

            browser = await self._browsers.launch(playwright, headless=True)
            try:
                for item in request.lessons:
                    if self._cancelled:
                        failed.extend(entry.lesson.title for entry in request.lessons[downloaded:])
                        break

                    emit(
                        DownloadEvent(
                            DownloadEventType.LESSON_STARTED,
                            message=f"Загружаю: {item.lesson.title}",
                            stage="lesson",
                            lesson=item.lesson.title,
                        )
                    )
                    success = False
                    for authentication_attempt in range(2):
                        try:
                            success = await self._download_lesson(
                                browser,
                                item,
                                request.save_path,
                                request.quality.value,
                                emit,
                            )
                            break
                        except _AuthenticationExpired:
                            await browser.close()
                            if authentication_attempt:
                                break
                            await self._ensure_authenticated(playwright, item.lesson.url, emit)
                            browser = await self._browsers.launch(playwright, headless=True)

                    if success:
                        downloaded += 1
                        emit(
                            DownloadEvent(
                                DownloadEventType.LESSON_COMPLETED,
                                message=f"Готово: {item.lesson.title}",
                                stage="lesson",
                                lesson=item.lesson.title,
                            )
                        )
                    else:
                        failed.append(item.lesson.title)
                        emit(
                            DownloadEvent(
                                DownloadEventType.LESSON_FAILED,
                                message=f"Не удалось скачать: {item.lesson.title}",
                                stage="lesson",
                                lesson=item.lesson.title,
                                level="error",
                            )
                        )
            finally:
                with contextlib.suppress(PlaywrightError):
                    await browser.close()

        summary = DownloadSummary(
            total=len(request.lessons),
            downloaded=downloaded,
            failed=tuple(failed),
        )
        emit(
            DownloadEvent(
                DownloadEventType.SUMMARY,
                message=f"Загружено: {summary.downloaded} из {summary.total}",
                stage="summary",
                current=summary.downloaded,
                total=summary.total,
                level="success" if summary.successful else "warning",
            )
        )
        return summary

    async def _ensure_authenticated(self, playwright, url: str, emit: EventHandler) -> None:
        browser = await self._browsers.launch(playwright, headless=True)
        try:
            page = browser.pages[0] if browser.pages else await browser.new_page()
            await self._open_page(page, url, "страницу для проверки авторизации", emit)
            needs_auth = await self._authentication_required(page)
        finally:
            await browser.close()

        if not needs_auth:
            emit(
                DownloadEvent(
                    DownloadEventType.AUTHENTICATED,
                    message="Авторизация активна",
                    stage="authentication",
                )
            )
            return

        emit(
            DownloadEvent(
                DownloadEventType.AUTH_REQUIRED,
                message="Требуется вход в GetCourse",
                stage="authentication",
            )
        )
        await asyncio.sleep(5)
        browser = await self._browsers.launch(playwright, headless=False)
        try:
            page = browser.pages[0] if browser.pages else await browser.new_page()
            await self._open_page(page, url, "страницу входа", emit)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, input)
        finally:
            await browser.close()
        emit(
            DownloadEvent(
                DownloadEventType.AUTHENTICATED,
                message="Авторизация выполнена",
                stage="authentication",
                level="success",
            )
        )

    async def _download_lesson(
        self,
        browser,
        item: SelectedLesson,
        save_root: Path,
        quality: str,
        emit: EventHandler,
    ) -> bool:
        page = await browser.new_page()
        master_urls_seen: set[str] = set()
        master_playlists: list[tuple[str, str]] = []

        async def on_response(response) -> None:
            url = response.url
            if not is_master_playlist_url(url) or url in master_urls_seen:
                return
            master_urls_seen.add(url)
            try:
                text = await asyncio.wait_for(response.text(), timeout=15)
                master_playlists.append((url, text))
            except Exception:
                return

        page.on("response", lambda response: asyncio.create_task(on_response(response)))

        try:
            await self._open_page(page, item.lesson.url, "страницу урока", emit)
            if await self._authentication_required(page):
                raise _AuthenticationExpired

            emit(
                DownloadEvent(
                    DownloadEventType.LOG,
                    message="Получаю master playlist",
                    stage="playlist",
                    lesson=item.lesson.title,
                )
            )
            started_at = time.monotonic()
            while not master_playlists and time.monotonic() - started_at < 30:
                if self._cancelled:
                    return False
                await asyncio.sleep(0.5)

            if not master_playlists:
                emit(
                    DownloadEvent(
                        DownloadEventType.ERROR,
                        message="Master playlist не получен",
                        stage="playlist",
                        lesson=item.lesson.title,
                    )
                )
                return False

            course_path = save_root / sanitize_filename(item.course_title, fallback="course")
            lesson_name = sanitize_filename(item.lesson.title)
            processed: set[str] = set()
            downloaded = False
            video_count = 0
            saved_single = False
            idle_since = time.monotonic()

            while True:
                pending = [(url, text) for url, text in master_playlists if url not in processed]
                if not pending:
                    if time.monotonic() - idle_since >= 5:
                        break
                    await asyncio.sleep(0.5)
                    continue

                for master_url, master_text in pending:
                    processed.add(master_url)
                    video_count += 1
                    qualities = parse_master_playlist(master_text, master_url)
                    selected_url = select_quality_url(qualities, quality)
                    if not selected_url:
                        emit(
                            DownloadEvent(
                                DownloadEventType.ERROR,
                                message="Не удалось подобрать качество",
                                stage="quality",
                                lesson=item.lesson.title,
                            )
                        )
                        continue

                    if len(master_playlists) > 1:
                        output = course_path / lesson_name / f"video_{video_count}"
                    else:
                        saved_single = True
                        output = course_path / lesson_name

                    downloaded = (
                        await self._hls.download(selected_url, output, item.lesson.title, emit)
                        or downloaded
                    )
                idle_since = time.monotonic()

            if saved_single and len(master_playlists) > 1:
                single_path = (course_path / lesson_name).with_suffix(".mp4")
                if single_path.exists():
                    video_dir = course_path / lesson_name
                    video_dir.mkdir(parents=True, exist_ok=True)
                    os.replace(single_path, video_dir / "video_1.mp4")
            return downloaded
        finally:
            with contextlib.suppress(PlaywrightError):
                await page.close()

    @staticmethod
    async def _authentication_required(page: Any) -> bool:
        with contextlib.suppress(PlaywrightError):
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        await page.wait_for_timeout(500)
        current_url = page.url.lower()
        return "login" in current_url or "required=true" in current_url

    @staticmethod
    async def _open_page(
        page: Any,
        url: str,
        purpose: str,
        emit: EventHandler,
        attempts: int = 3,
    ) -> None:
        last_error: PlaywrightError | None = None
        for attempt in range(1, attempts + 1):
            try:
                await page.goto(url, wait_until="commit", timeout=60_000)
                return
            except (PlaywrightTimeoutError, PlaywrightError) as error:
                last_error = error
                if attempt < attempts:
                    emit(
                        DownloadEvent(
                            DownloadEventType.LOG,
                            message=(
                                f"Не удалось открыть {purpose}. Повтор {attempt}/{attempts - 1}"
                            ),
                            stage="network",
                            level="warning",
                        )
                    )
                    await asyncio.sleep(attempt * 3)
        raise RuntimeError(
            "Не удалось открыть страницу: сайт не отвечает. Проверьте интернет и повторите."
        ) from last_error
