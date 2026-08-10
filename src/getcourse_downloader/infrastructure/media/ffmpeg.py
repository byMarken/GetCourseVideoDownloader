from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from getcourse_downloader.infrastructure.platform.paths import AppPaths


class FfmpegMuxer:
    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths

    def executable(self) -> str:
        bundled = self._paths.resources / "ffmpeg.exe"
        if bundled.is_file():
            return str(bundled.resolve())
        system = shutil.which("ffmpeg")
        if system:
            return system
        raise FileNotFoundError(
            "ffmpeg не найден. Установите его в PATH или поместите ffmpeg.exe в resources/."
        )

    async def mux(self, source: Path, destination: Path) -> tuple[bool, str]:
        flags = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            self.executable(),
            "-y",
            "-i",
            str(source),
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            str(destination),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            creationflags=flags,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except TimeoutError:
            process.kill()
            await process.wait()
            return False, "ffmpeg завис (таймаут 5 минут)"
        if process.returncode != 0:
            return False, stderr.decode("utf-8", errors="replace")[-300:]
        return True, ""
