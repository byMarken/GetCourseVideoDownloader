from __future__ import annotations

from getcourse_downloader.application.ports.discovery import (
    AuthRequiredCallback,
    CourseDiscoveredCallback,
)
from getcourse_downloader.application.use_cases.discover_courses import DiscoverCourses
from getcourse_downloader.domain.models import Course


class StartController:
    def __init__(self, discover_courses: DiscoverCourses) -> None:
        self._discover_courses = discover_courses

    async def discover(
        self,
        url: str,
        *,
        on_auth_required: AuthRequiredCallback,
        on_course_discovered: CourseDiscoveredCallback,
    ) -> list[Course]:
        return await self._discover_courses.execute(
            url,
            on_auth_required=on_auth_required,
            on_course_discovered=on_course_discovered,
        )
