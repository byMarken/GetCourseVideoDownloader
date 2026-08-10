from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiohttp

from getcourse_downloader.application.ports.download import EventHandler
from getcourse_downloader.domain.events import DownloadEvent, DownloadEventType
from getcourse_downloader.infrastructure.media.ffmpeg import FfmpegMuxer


def extract_quality(url: str) -> int:
    path = url.split("?", 1)[0]
    numeric_parts = [part for part in path.split("/") if part.isdigit()]
    return int(numeric_parts[-1]) if numeric_parts else 0


def parse_master_playlist(text: str, master_url: str) -> dict[int, str]:
    import re

    qualities: dict[int, str] = {}
    last_resolution: int | None = None
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            match = re.search(r"RESOLUTION=\d+x(\d+)", line)
            last_resolution = int(match.group(1)) if match else None
        elif line and not line.startswith("#"):
            absolute_url = urljoin(master_url, line)
            quality = extract_quality(absolute_url) or last_resolution or 0
            if quality > 0:
                qualities[quality] = absolute_url
            last_resolution = None
    return qualities


def select_quality_url(qualities: dict[int, str], quality: str) -> str | None:
    if not qualities:
        return None
    available = sorted(qualities)
    if not quality or quality == "auto":
        return qualities[available[-1]]
    target = int(quality)
    if target in qualities:
        return qualities[target]
    below = [candidate for candidate in available if candidate < target]
    return qualities[below[-1] if below else available[0]]


def extract_segment_urls(playlist: str, playlist_url: str) -> list[str]:
    return [
        urljoin(playlist_url, line.strip())
        for line in playlist.splitlines()
        if line.strip() and not line.startswith("#") and (".bin" in line or ".ts" in line)
    ]


class HlsDownloader:
    def __init__(self, muxer: FfmpegMuxer, *, concurrency: int = 10) -> None:
        self._muxer = muxer
        self._concurrency = concurrency

    async def download(
        self,
        playlist_url: str,
        output_without_suffix: Path,
        lesson_title: str,
        emit: EventHandler,
    ) -> bool:
        output_mp4 = output_without_suffix.with_suffix(".mp4")
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        parts = urlsplit(playlist_url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"{parts.scheme}://{parts.netloc}/",
        }
        timeout = aiohttp.ClientTimeout(
            total=600,
            connect=15,
            sock_connect=15,
            sock_read=15,
        )

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            try:
                async with session.get(playlist_url) as response:
                    response.raise_for_status()
                    playlist = await response.text()
            except Exception as error:
                emit(
                    DownloadEvent(
                        DownloadEventType.ERROR,
                        message=f"Не удалось получить плейлист: {error}",
                        stage="playlist",
                        lesson=lesson_title,
                    )
                )
                return False

            segment_urls = extract_segment_urls(playlist, playlist_url)
            total = len(segment_urls)
            if not total:
                emit(
                    DownloadEvent(
                        DownloadEventType.ERROR,
                        message="В плейлисте нет сегментов",
                        stage="segments",
                        lesson=lesson_title,
                    )
                )
                return False

            with tempfile.TemporaryDirectory(prefix="gcd-hls-") as temporary:
                temporary_dir = Path(temporary)
                semaphore = asyncio.Semaphore(self._concurrency)
                completed = 0
                last_report = float("-inf")

                async def download_segment(index: int, url: str) -> Path | None:
                    nonlocal completed, last_report
                    async with semaphore:
                        for attempt in range(3):
                            try:
                                async with session.get(url) as response:
                                    response.raise_for_status()
                                    content = await response.read()
                                path = temporary_dir / f"{index:06d}.bin"
                                path.write_bytes(content)
                                completed += 1
                                now = time.monotonic()
                                if now - last_report >= 0.5 or completed == total:
                                    last_report = now
                                    emit(
                                        DownloadEvent(
                                            DownloadEventType.PROGRESS,
                                            message=f"Сегменты: {completed}/{total}",
                                            stage="segments",
                                            lesson=lesson_title,
                                            current=completed,
                                            total=total,
                                        )
                                    )
                                return path
                            except (TimeoutError, aiohttp.ClientError, OSError):
                                if attempt == 2:
                                    return None
                                await asyncio.sleep(2**attempt)
                    return None

                results = await asyncio.gather(
                    *(download_segment(index, url) for index, url in enumerate(segment_urls))
                )
                if any(path is None for path in results):
                    failed_count = sum(path is None for path in results)
                    emit(
                        DownloadEvent(
                            DownloadEventType.ERROR,
                            message=f"Не удалось скачать сегментов: {failed_count}",
                            stage="segments",
                            lesson=lesson_title,
                        )
                    )
                    return False

                transport_stream = temporary_dir / "video.ts"
                with transport_stream.open("wb") as destination:
                    for segment in results:
                        assert segment is not None
                        destination.write(segment.read_bytes())

                temporary_output = output_mp4.with_name(f".{output_mp4.name}.part.mp4")
                temporary_output.unlink(missing_ok=True)
                emit(
                    DownloadEvent(
                        DownloadEventType.LOG,
                        message="Собираю MP4 через FFmpeg",
                        stage="ffmpeg",
                        lesson=lesson_title,
                    )
                )
                success, error_message = await self._muxer.mux(transport_stream, temporary_output)
                if not success:
                    temporary_output.unlink(missing_ok=True)
                    emit(
                        DownloadEvent(
                            DownloadEventType.ERROR,
                            message=f"Ошибка FFmpeg: {error_message}",
                            stage="ffmpeg",
                            lesson=lesson_title,
                        )
                    )
                    return False
                os.replace(temporary_output, output_mp4)
                return True
