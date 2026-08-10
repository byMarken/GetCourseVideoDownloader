import asyncio
from collections.abc import Sequence

import pytest

from getcourse_downloader.application.use_cases.discover_courses import DiscoverCourses
from getcourse_downloader.domain.errors import ExternalServiceError
from getcourse_downloader.domain.models import Course, Lesson


class _Discoverer:
    def __init__(self, courses: Sequence[Course]) -> None:
        self._courses = courses

    async def discover(self, *_: object, **__: object) -> Sequence[Course]:
        return self._courses


class _Repository:
    def __init__(self) -> None:
        self.saved: list[Course] | None = None

    def save(self, courses: Sequence[Course]) -> None:
        self.saved = list(courses)


def test_empty_discovery_does_not_overwrite_previous_courses():
    repository = _Repository()
    use_case = DiscoverCourses(_Discoverer([]), repository)  # type: ignore[arg-type]

    with pytest.raises(ExternalServiceError, match="не найдено"):
        asyncio.run(use_case.execute("https://school.example/teach/control"))

    assert repository.saved is None


def test_successful_discovery_is_saved():
    expected = [
        Course(
            title="Курс",
            lessons=(Lesson(title="Урок", url="https://school.example/lesson/1"),),
        )
    ]
    repository = _Repository()
    use_case = DiscoverCourses(_Discoverer(expected), repository)  # type: ignore[arg-type]

    actual = asyncio.run(use_case.execute("https://school.example/teach/control"))

    assert actual == expected
    assert repository.saved == expected
