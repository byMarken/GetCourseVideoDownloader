import sys
from pathlib import Path

from getcourse_downloader.infrastructure.platform import paths

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_is_frozen_false_by_default():
    assert paths.is_frozen() is False


def test_project_root_dev(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.project_root() == _PROJECT_ROOT


def test_project_root_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert paths.project_root() == tmp_path


def test_app_paths_use_platform_data_and_bundled_resources(monkeypatch, tmp_path):
    user_root = tmp_path / "user-data"
    monkeypatch.setattr(paths, "user_data_path", lambda *args, **kwargs: user_root)
    discovered = paths.AppPaths.discover()
    assert discovered.data == user_root / "data"
    assert discovered.session == user_root / "browser-profile"
    assert discovered.resources == _PROJECT_ROOT / "resources"


def test_ensure_runtime_directories(monkeypatch, tmp_path):
    user_root = tmp_path / "user-data"
    monkeypatch.setattr(paths, "user_data_path", lambda *args, **kwargs: user_root)
    discovered = paths.AppPaths.discover()
    discovered.ensure_runtime_directories()
    assert discovered.data.is_dir()
    assert discovered.session.is_dir()
