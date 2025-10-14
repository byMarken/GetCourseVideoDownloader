import os, re, sys, tempfile, aiohttp, asyncio, argparse, subprocess
from tqdm import tqdm
from utils_config import get_env_config, get_quality_list

cfg = get_env_config()
MAX_PARALLEL_DOWNLOADS = cfg["max_parallel"]

def modify_url_quality(url, desired_quality):
    """Заменяет разрешение в ссылке (например, /720? → /1080?)"""
    pattern = r"/(360|480|720|1080)\?"
    if re.search(pattern, url):
        return re.sub(pattern, f"/{desired_quality}?", url)
    return url.replace("/media/", f"/media/{desired_quality}?")

async def fetch(session, url, dest, desc=None):
    async with session.get(url) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(dest, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, desc=desc or "Загрузка", leave=False
        ) as bar:
            async for chunk in r.content.iter_chunked(64 * 1024):
                f.write(chunk)
                bar.update(len(chunk))

async def download_segment(session, url, dest, sem):
    async with sem:
        for _ in range(3):
            try:
                await fetch(session, url, dest, f"Сегмент {os.path.basename(dest)}")
                return
            except Exception as e:
                print(f"⚠️ Ошибка сегмента: {e}, повтор...")
                await asyncio.sleep(1)

async def convert_to_mp4_async(result_file):
    mp4_file = result_file + ".mp4"
    print("🎞 Конвертация в MP4...")
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", result_file, "-c", "copy", mp4_file,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode == 0:
        print(f"✅ Конвертация завершена: {mp4_file}")
        os.remove(result_file)
    else:
        print("❌ Ошибка ffmpeg:", stderr.decode("utf-8", errors="ignore"))

async def main_download(url, result_file):
    connector = aiohttp.TCPConnector(limit=MAX_PARALLEL_DOWNLOADS)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=60)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        with tempfile.TemporaryDirectory() as tmpdir:
            main_playlist = os.path.join(tmpdir, "main.m3u8")
            await fetch(session, url, main_playlist, "Основной плейлист")

            with open(main_playlist, encoding="utf-8") as f:
                content = f.read().strip()

            if re.search(r"https?://.*\.(ts|bin)", content):
                ts_urls = [line.strip() for line in content.splitlines() if line.startswith("http")]
            else:
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                tail = lines[-1]
                if not tail.startswith("http"):
                    raise aiohttp.ClientError(" Плейлист не найден.")
                second_playlist = os.path.join(tmpdir, "second.m3u8")
                await fetch(session, tail, second_playlist, "Вторичный плейлист")
                with open(second_playlist, encoding="utf-8") as f2:
                    ts_urls = [line.strip() for line in f2 if line.startswith("http")]

            if not ts_urls:
                raise aiohttp.ClientError("❌ Не удалось извлечь сегменты из ссылки.")

            print(f"📦 Сегментов: {len(ts_urls)}")

            sem = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)
            tmp_ts = [os.path.join(tmpdir, f"{i:05}.ts") for i in range(len(ts_urls))]
            await asyncio.gather(*[
                download_segment(session, ts_urls[i], tmp_ts[i], sem)
                for i in range(len(ts_urls))
            ])

            print("🔗 Объединение...")
            with open(result_file, "wb") as out:
                for ts in tqdm(sorted(tmp_ts), desc="Объединение", unit="файл"):
                    with open(ts, "rb") as f:
                        out.write(f.read())

            print("✅ Скачано:", result_file)
            await convert_to_mp4_async(result_file)

async def try_download_with_quality(url, result_file):
    quality_setting = cfg["quality"]
    print(f"🎚 Настройка качества: {quality_setting.upper()}")

    qualities = get_quality_list(quality_setting)
    for q in qualities:
        try_url = modify_url_quality(url, q)
        print(f"📺 Пробую качество: {q}p")
        try:
            await main_download(try_url, result_file)
            print(f"✅ Успешно скачано в качестве {q}p")
            return
        except Exception as e:
            print(f"⚠️ Ошибка при {q}p: {e}")
    print("❌ Не удалось скачать ни в одном качестве.")

if __name__ == "__main__":
    while True:
        u = input("Введите ссылку на m3u8: ").strip()
        f = input("Введите имя файла (без .mp4): ").strip()
        asyncio.run(try_download_with_quality(u, f))
