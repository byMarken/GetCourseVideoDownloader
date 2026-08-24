from collections.abc import Sequence
from typing import Protocol

from getcourse_downloader.domain.models import Course, Settings


class CourseRepository(Protocol):
    def load(self) -> list[Course]: ...

    def save(self, courses: Sequence[Course]) -> None: ...

    def has_courses(self) -> bool: ...

    def delete(self) -> None: ...


class SettingsRepository(Protocol):
    def load(self) -> Settings: ...

    def save(self, settings: Settings) -> None: ...
