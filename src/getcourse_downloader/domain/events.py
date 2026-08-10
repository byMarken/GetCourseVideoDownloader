from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from getcourse_downloader.domain.errors import InvalidDataError


class DownloadEventType(StrEnum):
    LOG = "log"
    PROGRESS = "progress"
    AUTH_REQUIRED = "auth_required"
    AUTHENTICATED = "authenticated"
    LESSON_STARTED = "lesson_started"
    LESSON_COMPLETED = "lesson_completed"
    LESSON_FAILED = "lesson_failed"
    SUMMARY = "summary"
    ERROR = "error"


class VideoCheckStatus(StrEnum):
    CHECKING = "checking"
    VIDEO = "video"
    NO_VIDEO = "no_video"


@dataclass(frozen=True, slots=True)
class VideoCheckEvent:
    lesson_url: str
    lesson_title: str
    status: VideoCheckStatus
    checked: int
    total: int
    video_count: int


@dataclass(frozen=True, slots=True)
class DownloadEvent:
    type: DownloadEventType
    message: str = ""
    stage: str = ""
    lesson: str = ""
    current: int | None = None
    total: int | None = None
    level: str = "info"

    def to_json(self) -> str:
        payload = {"protocol_version": 1, **asdict(self)}
        payload["type"] = self.type.value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DownloadEvent:
        try:
            event_type = DownloadEventType(str(data["type"]))
        except (KeyError, ValueError) as error:
            raise InvalidDataError("Неизвестный тип события worker") from error

        def optional_int(key: str) -> int | None:
            value = data.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        return cls(
            type=event_type,
            message=str(data.get("message", "")),
            stage=str(data.get("stage", "")),
            lesson=str(data.get("lesson", "")),
            current=optional_int("current"),
            total=optional_int("total"),
            level=str(data.get("level", "info")),
        )

    @classmethod
    def from_json(cls, line: str) -> DownloadEvent:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise InvalidDataError("Worker вернул некорректный JSON") from error
        if not isinstance(payload, dict):
            raise InvalidDataError("Событие worker должно быть JSON-объектом")
        return cls.from_dict(payload)
