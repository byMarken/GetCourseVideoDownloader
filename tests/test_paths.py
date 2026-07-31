import sys
from pathlib import Path

from app.utils import paths

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_is_frozen_false_by_default():
    assert paths.is_frozen() is False


def test_app_dir_dev(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.app_dir() == _PROJECT_ROOT


def test_app_dir_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert paths.app_dir() == tmp_path


def test_data_dir_dev(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.data_dir() == _PROJECT_ROOT / "app" / "data"


def test_data_dir_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert paths.data_dir() == tmp_path / "data"


def test_resources_dir_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert paths.resources_dir() == tmp_path / "resources"


def test_session_data_dir_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert paths.session_data_dir() == tmp_path / "session_data"


def test_ensure_data_dir_creates(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    result = paths.ensure_data_dir()
    assert result == tmp_path / "data"
    assert result.is_dir()
