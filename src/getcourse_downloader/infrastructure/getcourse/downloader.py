from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from getcourse_downloader.application.ports.download import EventHandler
from getcourse_downloader.domain.events import DownloadEvent, DownloadEventType
from getcourse_downloader.domain.models import DownloadRequest, DownloadSummary, SelectedLesson
from getcourse_downloader.infrastructure.browser.playwright import PlaywrightBrowserFactory
from getcourse_downloader.infrastructure.getcourse.video_signals import (
    VIDEO_PLAYER_SELECTOR,
    is_hls_playlist_url,
)
from getcourse_downloader.infrastructure.media.hls import (
    HlsDownloader,
    HlsDownloadStatus,
    canonical_media_url,
    extract_quality,
    is_hls_master_playlist,
    is_hls_playlist,
    media_family_url,
    select_stream_playlist_url,
)
from getcourse_downloader.infrastructure.storage.course_site import generate_course_site
from getcourse_downloader.infrastructure.storage.download_catalog import (
    DownloadedMedia,
    JsonDownloadCatalog,
)
from getcourse_downloader.infrastructure.storage.filenames import (
    collision_safe_component,
    collision_safe_stem,
    safe_lesson_output_stem,
)

PLAYLIST_WAIT_SECONDS = 30.0
PLAYLIST_QUIET_SECONDS = 3.0


class _AuthenticationExpired(RuntimeError):
    pass


class _LessonStatus(StrEnum):
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"
    NO_VIDEO = "no_video"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class _LessonResult:
    status: _LessonStatus
    media: tuple[DownloadedMedia, ...] = ()


@dataclass(frozen=True, slots=True)
class _Playlist:
    url: str
    text: str


class PlaywrightDownloadGateway:
    """Open only selected lessons, detect their streams, and download their media."""

    def __init__(
        self,
        browsers: PlaywrightBrowserFactory,
        hls: HlsDownloader,
        catalog: JsonDownloadCatalog | None = None,
        diagnostic_log: Path | None = None,
    ) -> None:
        self._browsers = browsers
        self._hls = hls
        self._catalog = catalog
        self._diagnostic_log = diagnostic_log
        self._cancelled = threading.Event()
        self._authentication_continued = threading.Event()

    def _diagnostic(self, event: str, **details: object) -> None:
        if self._diagnostic_log is None:
            return
        payload = {"time": time.time(), "event": event, **details}
        try:
            self._diagnostic_log.parent.mkdir(parents=True, exist_ok=True)
            with self._diagnostic_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def run(self, request: DownloadRequest, on_event: EventHandler) -> DownloadSummary:
        self._cancelled.clear()
        self._authentication_continued.clear()
        return asyncio.run(self._run_async(request, on_event))

    def continue_authentication(self) -> None:
        self._authentication_continued.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._authentication_continued.set()

    def shutdown(self, timeout: float = 6.0) -> None:
        del timeout
        self.cancel()

    @staticmethod
    def _event(
        item: SelectedLesson,
        event_type: DownloadEventType,
        message: str,
        *,
        stage: str = "lesson",
        level: str = "info",
        quality: str = "",
    ) -> DownloadEvent:
        return DownloadEvent(
            event_type,
            message=message,
            stage=stage,
            lesson=item.lesson.title,
            lesson_url=item.lesson.url,
            course_path=item.course_path,
            quality=quality,
            level=level,
        )

    @staticmethod
    def _quality_label(media: tuple[DownloadedMedia, ...]) -> str:
        qualities = list(dict.fromkeys(item.quality for item in media if item.quality))
        return ", ".join(qualities)

    async def _existing_result(
        self,
        item: SelectedLesson,
        output_stem: Path,
    ) -> _LessonResult | None:
        if self._catalog:
            catalogued = self._catalog.find(item.lesson.url, output_stem)
            if catalogued:
                return _LessonResult(_LessonStatus.SKIPPED, catalogued)

        direct = output_stem.parent / f"{output_stem.name}.mp4"
        try:
            exists = direct.is_file() and direct.stat().st_size > 0
        except OSError:
            exists = False
        if not exists:
            return None
        quality = await self._hls.probe_quality(direct)
        media = (DownloadedMedia(direct, quality),)
        if self._catalog:
            self._catalog.save(item.lesson.url, output_stem, media)
        return _LessonResult(_LessonStatus.SKIPPED, media)

    @staticmethod
    def _output_exists(stem: Path) -> bool:
        direct = stem.parent / f"{stem.name}.mp4"
        return direct.is_file() and direct.stat().st_size > 0

    @staticmethod
    def _output_stems(request: DownloadRequest) -> list[Path]:
        initial_stems = [
            safe_lesson_output_stem(
                request.save_path,
                item.course_path,
                item.lesson.title,
            )
            for item in request.lessons
        ]
        relative_parts = [list(stem.relative_to(request.save_path).parts) for stem in initial_stems]

        max_course_depth = max((len(item.course_path) for item in request.lessons), default=0)
        for depth in range(max_course_depth):
            groups: dict[tuple[tuple[str, ...], str], list[int]] = {}
            for index, item in enumerate(request.lessons):
                if depth >= len(item.course_path):
                    continue
                key = (
                    tuple(part.casefold() for part in relative_parts[index][:depth]),
                    relative_parts[index][depth].casefold(),
                )
                groups.setdefault(key, []).append(index)
            for indexes in groups.values():
                raw_prefixes = {
                    request.lessons[index].course_path[: depth + 1] for index in indexes
                }
                if len(raw_prefixes) < 2:
                    continue
                for index in indexes:
                    identity = "\x1f".join(request.lessons[index].course_path[: depth + 1])
                    relative_parts[index][depth] = collision_safe_component(
                        relative_parts[index][depth],
                        identity,
                    )

        stems = [request.save_path.joinpath(*parts) for parts in relative_parts]
        counts = Counter(str(stem).casefold() for stem in stems)
        url_counts = Counter(item.lesson.url for item in request.lessons)
        return [
            (
                collision_safe_stem(
                    stems[index],
                    item.lesson.url
                    if url_counts[item.lesson.url] == 1
                    else f"{item.lesson.url}#{index}",
                )
                if counts[str(stems[index]).casefold()] > 1
                else stems[index]
            )
            for index, item in enumerate(request.lessons)
        ]

    async def _run_async(self, request: DownloadRequest, emit: EventHandler) -> DownloadSummary:
        downloaded = 0
        already_present = 0
        no_video = 0
        failed: list[str] = []
        cancelled = 0
        output_stems = self._output_stems(request)

        async with async_playwright() as playwright:
            pending: list[int] = []
            for index, item in enumerate(request.lessons):
                if self._cancelled.is_set():
                    cancelled = len(request.lessons) - index
                    break
                existing = await self._existing_result(item, output_stems[index])
                if existing is None:
                    pending.append(index)
                    continue
                already_present += 1
                emit(
                    self._event(
                        item,
                        DownloadEventType.LESSON_SKIPPED,
                        f"Уже скачано: {item.lesson.title}",
                        level="success",
                        quality=self._quality_label(existing.media),
                    )
                )

            browser = None
            try:
                if pending and not self._cancelled.is_set():
                    browser = await self._launch_authenticated_context(
                        playwright,
                        request.lessons[pending[0]].lesson.url,
                        emit,
                    )
                for pending_position, index in enumerate(pending):
                    item = request.lessons[index]
                    if self._cancelled.is_set() or browser is None:
                        cancelled += len(pending) - pending_position
                        break

                    emit(self._event(item, DownloadEventType.LESSON_STARTED, "Проверяю урок"))
                    result = _LessonResult(_LessonStatus.FAILED)
                    for authentication_attempt in range(2):
                        try:
                            result = await self._download_lesson(
                                browser,
                                item,
                                output_stems[index],
                                request.quality.value,
                                emit,
                            )
                            break
                        except _AuthenticationExpired:
                            await browser.close()
                            if authentication_attempt:
                                break
                            browser = await self._launch_authenticated_context(
                                playwright,
                                item.lesson.url,
                                emit,
                            )
                            if browser is None:
                                result = _LessonResult(_LessonStatus.CANCELLED)
                                break

                    if result.status is _LessonStatus.DOWNLOADED:
                        downloaded += 1
                        emit(
                            self._event(
                                item,
                                DownloadEventType.LESSON_COMPLETED,
                                f"Готово: {item.lesson.title}",
                                level="success",
                                quality=self._quality_label(result.media),
                            )
                        )
                        if self._catalog:
                            self._catalog.save(item.lesson.url, output_stems[index], result.media)
                    elif result.status is _LessonStatus.SKIPPED:
                        already_present += 1
                        emit(
                            self._event(
                                item,
                                DownloadEventType.LESSON_SKIPPED,
                                f"Уже скачано: {item.lesson.title}",
                                level="success",
                                quality=self._quality_label(result.media),
                            )
                        )
                        if self._catalog:
                            self._catalog.save(item.lesson.url, output_stems[index], result.media)
                    elif result.status is _LessonStatus.NO_VIDEO:
                        no_video += 1
                        emit(
                            self._event(
                                item,
                                DownloadEventType.LESSON_NO_VIDEO,
                                f"Видео не найдено: {item.lesson.title}",
                                level="warning",
                            )
                        )
                    elif result.status is _LessonStatus.CANCELLED:
                        cancelled += len(pending) - pending_position
                        break
                    else:
                        failed.append(item.lesson.title)
                        emit(
                            self._event(
                                item,
                                DownloadEventType.LESSON_FAILED,
                                f"Не удалось скачать: {item.lesson.title}",
                                level="error",
                            )
                        )
            finally:
                if browser is not None:
                    with contextlib.suppress(PlaywrightError):
                        await browser.close()

        site_path: Path | None = None
        try:
            site_path = generate_course_site(request, output_stems, self._catalog)
        except OSError as error:
            self._diagnostic("site_generation_failed", error=str(error))
        if site_path:
            emit(
                DownloadEvent(
                    DownloadEventType.LOG,
                    message=f"Локальный сайт обновлён: {site_path}",
                    stage="site",
                    level="success",
                )
            )

        summary = DownloadSummary(
            total=len(request.lessons),
            downloaded=downloaded,
            already_present=already_present,
            no_video=no_video,
            failed=tuple(failed),
            cancelled=cancelled,
        )
        emit(
            DownloadEvent(
                DownloadEventType.SUMMARY,
                message=(
                    f"Загружено: {summary.downloaded}; уже было: {summary.already_present}; "
                    f"без видео: {summary.no_video}; ошибок: {len(summary.failed)}"
                ),
                stage="summary",
                current=summary.processed,
                total=summary.total,
                downloaded=summary.downloaded,
                already_present=summary.already_present,
                no_video=summary.no_video,
                failed_count=len(summary.failed),
                cancelled=summary.cancelled,
                level="success" if summary.successful else "warning",
            )
        )
        return summary

    async def _launch_authenticated_context(
        self,
        playwright,
        url: str,
        emit: EventHandler,
    ):
        browser = await self._browsers.launch(playwright, headless=True)
        try:
            page = browser.pages[0] if browser.pages else await browser.new_page()
            opened = await self._open_page(
                page,
                url,
                "страницу для проверки авторизации",
                emit,
            )
            if not opened:
                await browser.close()
                return None
            needs_auth = await self._authentication_required(page)
        except Exception:
            with contextlib.suppress(PlaywrightError):
                await browser.close()
            raise

        if not needs_auth:
            emit(
                DownloadEvent(
                    DownloadEventType.AUTHENTICATED,
                    message="Авторизация активна",
                    stage="authentication",
                )
            )
            return browser

        await browser.close()

        browser = await self._browsers.launch(playwright, headless=False)
        try:
            page = browser.pages[0] if browser.pages else await browser.new_page()
            if not await self._open_page(page, url, "страницу входа", emit):
                return None
            while True:
                self._authentication_continued.clear()
                emit(
                    DownloadEvent(
                        DownloadEventType.AUTH_REQUIRED,
                        message="Войдите в GetCourse и нажмите «Продолжить»",
                        stage="authentication",
                    )
                )
                await asyncio.to_thread(self._authentication_continued.wait)
                if self._cancelled.is_set():
                    return None
                if not await self._open_page(
                    page,
                    url,
                    "страницу для проверки авторизации",
                    emit,
                ):
                    return None
                if not await self._authentication_required(page):
                    break
        finally:
            await browser.close()
        if self._cancelled.is_set():
            return None
        emit(
            DownloadEvent(
                DownloadEventType.AUTHENTICATED,
                message="Авторизация выполнена",
                stage="authentication",
                level="success",
            )
        )
        return await self._browsers.launch(playwright, headless=True)

    async def _download_lesson(
        self,
        browser,
        item: SelectedLesson,
        output_stem: Path,
        quality: str,
        emit: EventHandler,
    ) -> _LessonResult:
        existing = await self._existing_result(item, output_stem)
        if existing is not None:
            return existing

        page = await browser.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})
        playlists: dict[str, _Playlist] = {}
        response_tasks: set[asyncio.Task[None]] = set()
        last_playlist_at = 0.0

        async def on_response(response) -> None:
            nonlocal last_playlist_at
            url = response.url
            if not is_hls_playlist_url(url) or url in playlists:
                return
            try:
                text = await asyncio.wait_for(response.text(), timeout=15)
            except Exception:
                return
            if is_hls_master_playlist(text) or is_hls_playlist(text):
                playlists[url] = _Playlist(url, text)
                last_playlist_at = time.monotonic()
                self._diagnostic(
                    "playlist_captured",
                    lesson=item.lesson.url,
                    playlist=url,
                    quality=extract_quality(url),
                    master=is_hls_master_playlist(text),
                )

        def schedule_response(response) -> None:
            task = asyncio.create_task(on_response(response))
            response_tasks.add(task)
            task.add_done_callback(response_tasks.discard)

        page.on("response", schedule_response)

        try:
            if not await self._open_page(
                page,
                item.lesson.url,
                "страницу урока",
                emit,
                item=item,
            ):
                return _LessonResult(_LessonStatus.CANCELLED)
            if await self._authentication_required(page):
                raise _AuthenticationExpired

            player_present = await self._has_supported_player(page)
            await self._activate_players(page)
            started_at = time.monotonic()
            while time.monotonic() - started_at < PLAYLIST_WAIT_SECONDS:
                if self._cancelled.is_set():
                    return _LessonResult(_LessonStatus.CANCELLED)
                if playlists and time.monotonic() - last_playlist_at >= PLAYLIST_QUIET_SECONDS:
                    break
                await asyncio.sleep(0.25)

            if response_tasks:
                await asyncio.gather(*tuple(response_tasks), return_exceptions=True)

            page_media = await self._save_lesson_page(page, output_stem, item.lesson.url)

            if not playlists:
                player_present = player_present or await self._has_supported_player(page)
                if player_present:
                    emit(
                        self._event(
                            item,
                            DownloadEventType.ERROR,
                            "Плеер найден, но видеопоток не получен",
                            stage="playlist",
                            level="error",
                        )
                    )
                    return _LessonResult(_LessonStatus.FAILED)
                if page_media:
                    return _LessonResult(_LessonStatus.DOWNLOADED, (page_media,))
                return _LessonResult(_LessonStatus.NO_VIDEO)

            selected = self._select_playlist_urls(playlists.values(), quality)
            self._diagnostic(
                "playlist_selection",
                lesson=item.lesson.url,
                requested_quality=quality,
                captured=list(playlists),
                selected=selected,
            )

            if not selected:
                emit(
                    self._event(
                        item,
                        DownloadEventType.ERROR,
                        "Не удалось подобрать качество видео",
                        stage="quality",
                        level="error",
                    )
                )
                return _LessonResult(_LessonStatus.FAILED)

            download_results = []
            for video_index, playlist_url in enumerate(selected, start=1):
                output = output_stem if len(selected) == 1 else output_stem / f"video_{video_index}"
                result = await self._hls.download(
                    playlist_url,
                    output,
                    item.lesson.title,
                    emit,
                    lesson_url=item.lesson.url,
                    course_path=item.course_path,
                    requested_quality=quality,
                    video_index=video_index,
                    video_total=len(selected),
                    is_cancelled=self._cancelled.is_set,
                )
                download_results.append(result)
                if result.status is HlsDownloadStatus.CANCELLED or self._cancelled.is_set():
                    return _LessonResult(_LessonStatus.CANCELLED)

            statuses = [result.status for result in download_results]
            if any(status is HlsDownloadStatus.FAILED for status in statuses):
                return _LessonResult(_LessonStatus.FAILED)
            media = tuple(
                DownloadedMedia(result.output_path, result.quality)
                for result in download_results
                if result.output_path is not None
            )
            if page_media:
                media = (*media, page_media)
            if all(status is HlsDownloadStatus.ALREADY_PRESENT for status in statuses):
                return _LessonResult(_LessonStatus.SKIPPED, media)
            return _LessonResult(_LessonStatus.DOWNLOADED, media)
        finally:
            for task in response_tasks:
                task.cancel()
            if response_tasks:
                await asyncio.gather(*tuple(response_tasks), return_exceptions=True)
            with contextlib.suppress(PlaywrightError):
                await page.close()

    @staticmethod
    def _select_playlist_urls(playlists: Iterable[_Playlist], quality: str) -> list[str]:
        variants_by_video: dict[str, dict[int, str]] = {}
        for playlist in playlists:
            selected_url = select_stream_playlist_url(playlist.text, playlist.url, quality)
            if not selected_url:
                continue
            family = media_family_url(selected_url)
            variants = variants_by_video.setdefault(family, {})
            selected_quality = extract_quality(selected_url)
            if is_hls_master_playlist(playlist.text):
                variants[selected_quality] = selected_url
            else:
                variants.setdefault(selected_quality, selected_url)

        selected: dict[str, str] = {}
        for variants in variants_by_video.values():
            available = sorted(variants)
            if not available:
                continue
            if not quality or quality == "auto":
                chosen = available[-1]
            else:
                target = int(quality)
                below = [candidate for candidate in available if candidate <= target]
                chosen = below[-1] if below else available[0]
            url = variants[chosen]
            selected.setdefault(canonical_media_url(url), url)
        return [selected[key] for key in sorted(selected)]

    async def _activate_players(self, page: Any) -> None:
        frames = [page]
        with contextlib.suppress(Exception):
            frames.extend(frame for frame in page.frames if frame is not page.main_frame)
        for frame in frames:
            with contextlib.suppress(Exception):
                await frame.evaluate(
                    """() => {
                        for (const media of document.querySelectorAll('video, audio')) {
                            media.muted = true;
                            media.volume = 0;
                            media.setAttribute('playsinline', '');
                        }
                    }"""
                )
            for selector in (
                ".vjs-big-play-button",
                "button[aria-label*='Play']",
                "button[aria-label*='Воспроиз']",
                "div.vhi-root",
                "video",
            ):
                with contextlib.suppress(Exception):
                    element = await frame.query_selector(selector)
                    if element:
                        await element.click(timeout=3000)
                        break
        self._diagnostic("player_activated", frames=len(frames), viewport="1920x1080")

    @staticmethod
    async def _save_lesson_page(
        page: Any,
        output_stem: Path,
        lesson_url: str,
    ) -> DownloadedMedia | None:
        try:
            html = await page.content()
        except Exception:
            return None
        if not html.strip():
            return None
        base = f'<base href="{lesson_url}">'
        html = html.replace("<head>", f"<head>{base}", 1)
        output = output_stem.with_suffix(".html")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(html, encoding="utf-8")
        except OSError:
            return None
        return DownloadedMedia(output, "HTML")

    @staticmethod
    async def _has_supported_player(page: Any) -> bool:
        with contextlib.suppress(PlaywrightError):
            return await page.query_selector(VIDEO_PLAYER_SELECTOR) is not None
        return False

    @staticmethod
    async def _authentication_required(page: Any) -> bool:
        with contextlib.suppress(PlaywrightError):
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        await page.wait_for_timeout(500)
        current_url = page.url.lower()
        return "login" in current_url or "required=true" in current_url

    async def _goto_or_cancel(self, page: Any, url: str) -> bool:
        navigation = asyncio.create_task(page.goto(url, wait_until="commit", timeout=60_000))
        try:
            while not navigation.done():
                if self._cancelled.is_set():
                    navigation.cancel()
                    with contextlib.suppress(asyncio.CancelledError, PlaywrightError):
                        await navigation
                    return False
                await asyncio.sleep(0.1)
            await navigation
            return True
        except asyncio.CancelledError:
            navigation.cancel()
            with contextlib.suppress(asyncio.CancelledError, PlaywrightError):
                await navigation
            raise

    async def _open_page(
        self,
        page: Any,
        url: str,
        purpose: str,
        emit: EventHandler,
        attempts: int = 3,
        *,
        item: SelectedLesson | None = None,
    ) -> bool:
        last_error: PlaywrightError | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await self._goto_or_cancel(page, url)
            except (PlaywrightTimeoutError, PlaywrightError) as error:
                last_error = error
                if self._cancelled.is_set():
                    return False
                if attempt < attempts:
                    event = DownloadEvent(
                        DownloadEventType.LOG,
                        message=f"Не удалось открыть {purpose}. Повтор {attempt}/{attempts - 1}",
                        stage="network",
                        level="warning",
                    )
                    if item:
                        event = self._event(
                            item,
                            DownloadEventType.LOG,
                            event.message,
                            stage="network",
                            level="warning",
                        )
                    emit(event)
                    for _ in range(attempt * 30):
                        if self._cancelled.is_set():
                            return False
                        await asyncio.sleep(0.1)
        raise RuntimeError(
            "Не удалось открыть страницу: сайт не отвечает. Проверьте интернет и повторите."
        ) from last_error
