"""Настройки приложения и работа с переменными окружения."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

QUALITY_LEVELS = ["1080", "720", "480", "360"]

def get_env_config():
    """Загружает настройки из .env"""
    quality = os.getenv("QUALITY", "auto").lower()
    if quality not in ["auto"] + QUALITY_LEVELS:
        quality = "auto"

    headless = os.getenv("HEADLESS", "false").lower() in ("1", "true", "yes")
    max_parallel = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "4"))
    playlist_url = os.getenv("PLAYLIST_URL")

    raw_path = os.getenv("COURSES_SAVE_PATH", "Courses")
    raw_path = raw_path.strip().strip('"').strip("'")
    courses_save_path = os.path.normpath(raw_path)

    return {
        "quality": quality,
        "headless": headless,
        "courses_save_path": courses_save_path,
        "max_parallel": max_parallel,
        "playlist_url": playlist_url
    }

def get_quality_list(quality_setting: str):
    """Возвращает список качеств для загрузки"""
    if quality_setting == "auto":
        return QUALITY_LEVELS
    return [quality_setting]
