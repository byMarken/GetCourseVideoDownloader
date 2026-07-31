from __future__ import annotations

import shutil

from app.utils.paths import resources_dir


def get_ffmpeg_path() -> str:
    bundled = resources_dir() / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled.resolve())

    system = shutil.which("ffmpeg")
    if system:
        return system

    raise FileNotFoundError(
        "ffmpeg не найден.\n"
        "  • Установите ffmpeg (https://ffmpeg.org/) и добавьте его в PATH\n"
        "  • Или поместите ffmpeg.exe в папку resources/ рядом с программой"
    )
