from collections.abc import Callable
from typing import Protocol

from getcourse_downloader.domain.events import DownloadEvent
from getcourse_downloader.domain.models import DownloadRequest, DownloadSummary

EventHandler = Callable[[DownloadEvent], None]


class DownloadGateway(Protocol):
    def run(self, request: DownloadRequest, on_event: EventHandler) -> DownloadSummary: ...

    def continue_authentication(self) -> None: ...

    def cancel(self) -> None: ...
