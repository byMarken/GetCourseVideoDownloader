from getcourse_downloader.application.ports.discovery import (
    AuthRequiredCallback,
    CourseDiscoveredCallback,
    CourseDiscoverer,
)
from getcourse_downloader.application.ports.repositories import CourseRepository
from getcourse_downloader.domain.errors import DownloadConfigurationError, ExternalServiceError
from getcourse_downloader.domain.models import Course


class DiscoverCourses:
    def __init__(self, discoverer: CourseDiscoverer, repository: CourseRepository) -> None:
        self._discoverer = discoverer
        self._repository = repository

    async def execute(
        self,
        url: str,
        *,
        on_auth_required: AuthRequiredCallback | None = None,
        on_course_discovered: CourseDiscoveredCallback | None = None,
    ) -> list[Course]:
        normalized_url = url.strip()
        if not normalized_url.startswith(("http://", "https://")):
            raise DownloadConfigurationError("Ссылка должна начинаться с http:// или https://")

        courses = list(
            await self._discoverer.discover(
                normalized_url,
                on_auth_required=on_auth_required,
                on_course_discovered=on_course_discovered,
            )
        )
        if not courses:
            raise ExternalServiceError(
                "На странице не найдено доступных курсов или уроков. "
                "Проверьте ссылку и права текущего аккаунта."
            )
        self._repository.save(courses)
        return courses
