"""Инструменты для скачивания и конвертации m3u8 плейлистов."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from typing import Iterable

import aiohttp
from tqdm import tqdm

from utils_config import get_env_config, get_quality_list


cfg = get_env_config()
MAX_PARALLEL_DOWNLOADS = cfg["max_parallel"]


def modify_url_quality(url: str, desired_quality: str) -> str:
    """Заменяет разрешение в ссылке (например, /720? → /1080?)."""

    pattern = r"/(360|480|720|1080)\?"
    if re.search(pattern, url):
        return re.sub(pattern, f"/{desired_quality}?", url)
    return url.replace("/media/", f"/media/{desired_quality}?")

async def fetch(
    session: aiohttp.ClientSession,
    url: str,
    dest: str,
    desc: str | None = None,
) -> None:
    """Скачивает ресурс и показывает прогресс-бар."""

    async with session.get(url) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))

        with open(dest, "wb") as downloaded_file, tqdm(
            total=total,
            unit="B",
            unit_scale=True,
            desc=desc or "Загрузка",
            leave=False,
        ) as bar:
            async for chunk in response.content.iter_chunked(64 * 1024):
                downloaded_file.write(chunk)
                bar.update(len(chunk))


async def download_segment(
    session: aiohttp.ClientSession, url: str, dest: str, semaphore: asyncio.Semaphore
) -> None:
    """Скачивает сегмент с повторными попытками."""

    async with semaphore:
        for _ in range(3):
            try:
                await fetch(
                    session,
                    url,
                    dest,
                    f"Сегмент {os.path.basename(dest)}",
                )
                return
            except Exception as exc:  # noqa: BLE001
                print(f"⚠️ Ошибка сегмента: {exc}, повтор...")
                await asyncio.sleep(1)


async def convert_to_mp4_async(result_file: str) -> None:
    """Запускает ffmpeg для конвертации скачанного файла."""

    mp4_file = f"{result_file}.mp4"
    print("🎞 Конвертация в MP4...")
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        result_file,
        "-c",
        "copy",
        mp4_file,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode == 0:
        print(f"✅ Конвертация завершена: {mp4_file}")
        os.remove(result_file)
    else:
        print("❌ Ошибка ffmpeg:", stderr.decode("utf-8", errors="ignore"))

async def _read_playlist(path: str) -> str:
    with open(path, encoding="utf-8") as playlist:
        return playlist.read().strip()


def _parse_main_playlist(content: str) -> tuple[list[str], str | None]:
    if re.search(r"https?://.*\.(ts|bin)", content):
        urls = [line.strip() for line in content.splitlines() if line.startswith("http")]
        return urls, None

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return [], None
    tail = lines[-1]
    if not tail.startswith("http"):
        raise aiohttp.ClientError("❌ Плейлист не найден.")
    return [], tail


async def _load_second_playlist(
    session: aiohttp.ClientSession, tail_url: str, tmpdir: str
) -> list[str]:
    second_playlist = os.path.join(tmpdir, "second.m3u8")
    await fetch(session, tail_url, second_playlist, "Вторичный плейлист")
    with open(second_playlist, encoding="utf-8") as playlist:
        return [line.strip() for line in playlist if line.startswith("http")]


async def _merge_segments(result_file: str, segment_paths: Iterable[str]) -> None:
    print("🔗 Объединение...")
    with open(result_file, "wb") as merged_file:
        for ts_path in tqdm(sorted(segment_paths), desc="Объединение", unit="файл"):
            with open(ts_path, "rb") as segment:
                merged_file.write(segment.read())

    print("✅ Скачано:", result_file)
    await convert_to_mp4_async(result_file)


async def main_download(url: str, result_file: str) -> None:
    """Загружает все сегменты и объединяет их в файл."""

    connector = aiohttp.TCPConnector(limit=MAX_PARALLEL_DOWNLOADS)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=60)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        with tempfile.TemporaryDirectory() as tmpdir:
            main_playlist = os.path.join(tmpdir, "main.m3u8")
            await fetch(session, url, main_playlist, "Основной плейлист")

            content = await asyncio.to_thread(_read_playlist, main_playlist)
            ts_urls, nested_playlist_url = _parse_main_playlist(content)

            if nested_playlist_url:
                ts_urls = await _load_second_playlist(
                    session, nested_playlist_url, tmpdir
                )

            if not ts_urls:
                raise aiohttp.ClientError("❌ Не удалось извлечь сегменты из ссылки.")

            print(f"📦 Сегментов: {len(ts_urls)}")

            semaphore = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)
            tmp_ts = [os.path.join(tmpdir, f"{idx:05}.ts") for idx in range(len(ts_urls))]
            await asyncio.gather(
                *[
                    download_segment(session, ts_urls[idx], tmp_ts[idx], semaphore)
                    for idx in range(len(ts_urls))
                ]
            )

            await _merge_segments(result_file, tmp_ts)

async def try_download_with_quality(url: str, result_file: str) -> None:
    """Пробует скачать видео в указанном списке качеств."""

    quality_setting = cfg["quality"]
    print(f"🎚 Настройка качества: {quality_setting.upper()}")

    for quality in get_quality_list(quality_setting):
        try_url = modify_url_quality(url, quality)
        print(f"📺 Пробую качество: {quality}p")
        try:
            await main_download(try_url, result_file)
            print(f"✅ Успешно скачано в качестве {quality}p")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Ошибка при {quality}p: {exc}")

    print("❌ Не удалось скачать ни в одном качестве.")

if __name__ == "__main__":
    while True:
        u = input("Введите ссылку на m3u8: ").strip()
        f = input("Введите имя файла (без .mp4): ").strip()
        asyncio.run(try_download_with_quality(u, f))
