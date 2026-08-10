from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from getcourse_downloader.domain.errors import InvalidDataError


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidDataError(f"Поле {key!r} должно быть непустой строкой")
    return value.strip()


class VideoQuality(StrEnum):
    AUTO = "auto"
    P1080 = "1080"
    P720 = "720"
    P480 = "480"
    P360 = "360"

    @classmethod
    def parse(cls, value: object) -> VideoQuality:
        try:
            return cls(str(value or cls.AUTO))
        except ValueError as error:
            raise InvalidDataError(f"Неизвестное качество видео: {value!r}") from error


@dataclass(frozen=True, slots=True)
class Lesson:
    title: str
    url: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Lesson:
        return cls(title=_required_text(data, "title"), url=_required_text(data, "url"))

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url}


@dataclass(frozen=True, slots=True)
class Course:
    title: str
    lessons: tuple[Lesson, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Course:
        raw_lessons = data.get("lessons", [])
        if not isinstance(raw_lessons, list):
            raise InvalidDataError("Поле 'lessons' должно быть списком")
        return cls(
            title=_required_text(data, "course_title"),
            lessons=tuple(Lesson.from_dict(item) for item in raw_lessons if isinstance(item, dict)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "course_title": self.title,
            "lessons": [lesson.to_dict() for lesson in self.lessons],
        }


@dataclass(frozen=True, slots=True)
class SelectedLesson:
    course_title: str
    lesson: Lesson

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SelectedLesson:
        raw_lesson = data.get("lesson")
        if not isinstance(raw_lesson, dict):
            raise InvalidDataError("Поле 'lesson' должно быть объектом")
        return cls(
            course_title=_required_text(data, "course_title"),
            lesson=Lesson.from_dict(raw_lesson),
        )

    def to_dict(self) -> dict[str, object]:
        return {"course_title": self.course_title, "lesson": self.lesson.to_dict()}


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    lessons: tuple[SelectedLesson, ...]
    quality: VideoQuality
    save_path: Path

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DownloadRequest:
        raw_lessons = data.get("lessons")
        if not isinstance(raw_lessons, list):
            raise InvalidDataError("Поле 'lessons' должно быть списком")
        return cls(
            lessons=tuple(
                SelectedLesson.from_dict(item) for item in raw_lessons if isinstance(item, dict)
            ),
            quality=VideoQuality.parse(data.get("quality")),
            save_path=Path(_required_text(data, "save_path")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "lessons": [item.to_dict() for item in self.lessons],
            "quality": self.quality.value,
            "save_path": str(self.save_path),
        }


@dataclass(frozen=True, slots=True)
class DownloadSummary:
    total: int
    downloaded: int
    failed: tuple[str, ...] = ()

    @property
    def successful(self) -> bool:
        return self.total == self.downloaded and not self.failed


@dataclass(frozen=True, slots=True)
class Settings:
    save_path: str = "downloads"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Settings:
        save_path = data.get("save_path", "downloads")
        return cls(save_path=save_path if isinstance(save_path, str) else "downloads")

    def to_dict(self) -> dict[str, str]:
        return {"save_path": self.save_path}
