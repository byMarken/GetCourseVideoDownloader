from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def data_dir() -> Path:
    if is_frozen():
        return app_dir() / "data"
    return app_dir() / "app" / "data"


def resources_dir() -> Path:
    return app_dir() / "resources"


def session_data_dir() -> Path:
    return app_dir() / "session_data"


def ensure_data_dir() -> Path:
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    return data
