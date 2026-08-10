from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from getcourse_downloader.application.use_cases.download_lessons import DownloadLessons
from getcourse_downloader.domain.errors import DownloaderError, InvalidDataError
from getcourse_downloader.domain.events import DownloadEvent, DownloadEventType
from getcourse_downloader.domain.models import DownloadRequest
from getcourse_downloader.infrastructure.browser.playwright import PlaywrightBrowserFactory
from getcourse_downloader.infrastructure.getcourse.downloader import PlaywrightDownloadGateway
from getcourse_downloader.infrastructure.media.ffmpeg import FfmpegMuxer
from getcourse_downloader.infrastructure.media.hls import HlsDownloader
from getcourse_downloader.infrastructure.platform.paths import AppPaths
from getcourse_downloader.presentation.cli.console import configure_console_output


class JsonLineEventSink:
    def __call__(self, event: DownloadEvent) -> None:
        print(event.to_json(), flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Внутренний worker загрузки видео")
    parser.add_argument("--request-file", required=True, help="JSON-файл DownloadRequest")
    return parser


def _load_request(path: Path) -> DownloadRequest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidDataError("Не удалось прочитать запрос worker") from error
    if not isinstance(payload, dict):
        raise InvalidDataError("Запрос worker должен быть JSON-объектом")
    return DownloadRequest.from_dict(payload)


def main(argv: Sequence[str] | None = None) -> int:
    configure_console_output()
    sink = JsonLineEventSink()
    try:
        args = build_parser().parse_args(argv)
        request = _load_request(Path(args.request_file))
        paths = AppPaths.discover()
        gateway = PlaywrightDownloadGateway(
            PlaywrightBrowserFactory(paths),
            HlsDownloader(FfmpegMuxer(paths)),
        )
        summary = DownloadLessons(gateway).execute(request, sink)
        return 0 if summary.successful else 2
    except (DownloaderError, OSError, RuntimeError) as error:
        sink(
            DownloadEvent(
                DownloadEventType.ERROR,
                message=str(error),
                stage="worker",
                level="error",
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
