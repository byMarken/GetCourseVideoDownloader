from __future__ import annotations

import shutil
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_ffmpeg_path() -> str:
    bundled = _PROJECT_ROOT / "resources" / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled.resolve())

    # 2. System PATH
    system = shutil.which("ffmpeg")
    if system:
        return system

    # 3. Nothing found — raise a clear error
    raise FileNotFoundError(
        "ffmpeg не найден.\n"
        "  • Установите ffmpeg (https://ffmpeg.org/) и добавьте его в PATH\n"
        "  • Или поместите ffmpeg.exe в папку resources/ рядом с программой"
    )
