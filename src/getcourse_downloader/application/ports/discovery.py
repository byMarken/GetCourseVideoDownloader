from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from getcourse_downloader.domain.events import VideoCheckEvent
from getcourse_downloader.domain.models import Course

AuthRequiredCallback = Callable[[str], Awaitable[None]]
CourseDiscoveredCallback = Callable[[str, int], Awaitable[None]]
VideoCheckCallback = Callable[[VideoCheckEvent], Awaitable[None]]


class CourseDiscoverer(Protocol):
    async def discover(
        self,
        url: str,
        *,
        on_auth_required: AuthRequiredCallback | None = None,
        on_course_discovered: CourseDiscoveredCallback | None = None,
        on_video_check: VideoCheckCallback | None = None,
    ) -> Sequence[Course]: ...
