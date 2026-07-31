import shutil
from pathlib import Path

import pytest

from app.utils import ffmpeg


def test_get_ffmpeg_path_bundled(monkeypatch, tmp_path):
    (tmp_path / "ffmpeg.exe").write_bytes(b"")
    monkeypatch.setattr(ffmpeg, "resources_dir", lambda: tmp_path)
    assert ffmpeg.get_ffmpeg_path() == str((tmp_path / "ffmpeg.exe").resolve())


def test_get_ffmpeg_path_system(monkeypatch):
    monkeypatch.setattr(ffmpeg, "resources_dir", lambda: Path("nonexistent"))
    monkeypatch.setattr(shutil, "which", lambda name: "C:/ffmpeg/bin/ffmpeg.exe")
    assert ffmpeg.get_ffmpeg_path() == "C:/ffmpeg/bin/ffmpeg.exe"


def test_get_ffmpeg_path_not_found(monkeypatch):
    monkeypatch.setattr(ffmpeg, "resources_dir", lambda: Path("nonexistent"))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError):
        ffmpeg.get_ffmpeg_path()
