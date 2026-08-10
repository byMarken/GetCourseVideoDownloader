import pytest

from getcourse_downloader.domain.errors import InvalidDataError
from getcourse_downloader.domain.events import DownloadEvent, DownloadEventType
from getcourse_downloader.domain.models import Course, Lesson, VideoQuality


def test_course_json_compatibility():
    payload = {
        "course_title": "Курс",
        "lessons": [{"title": "Урок", "url": "https://example.com/lesson"}],
    }
    course = Course.from_dict(payload)
    assert course == Course("Курс", (Lesson("Урок", "https://example.com/lesson"),))
    assert course.to_dict() == payload


def test_event_json_round_trip():
    event = DownloadEvent(
        DownloadEventType.PROGRESS,
        message="Сегменты: 5/10",
        stage="segments",
        current=5,
        total=10,
    )
    assert DownloadEvent.from_json(event.to_json()) == event


def test_unknown_quality_rejected():
    with pytest.raises(InvalidDataError):
        VideoQuality.parse("4k")
