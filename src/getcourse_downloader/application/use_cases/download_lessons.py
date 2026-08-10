from getcourse_downloader.application.ports.download import DownloadGateway, EventHandler
from getcourse_downloader.domain.errors import DownloadConfigurationError
from getcourse_downloader.domain.models import DownloadRequest, DownloadSummary


class DownloadLessons:
    def __init__(self, gateway: DownloadGateway) -> None:
        self._gateway = gateway

    def execute(self, request: DownloadRequest, on_event: EventHandler) -> DownloadSummary:
        if not request.lessons:
            raise DownloadConfigurationError("Нет выбранных уроков")
        if not request.save_path.is_dir():
            raise DownloadConfigurationError("Папка для сохранения не существует")
        return self._gateway.run(request, on_event)

    def continue_authentication(self) -> None:
        self._gateway.continue_authentication()

    def cancel(self) -> None:
        self._gateway.cancel()
