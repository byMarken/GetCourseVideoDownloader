import sys
from pathlib import Path

import pytest

from getcourse_downloader.domain.events import DownloadEventType
from getcourse_downloader.domain.models import (
    DownloadRequest,
    Lesson,
    SelectedLesson,
    VideoQuality,
)
from getcourse_downloader.infrastructure.worker.subprocess_gateway import (
    SubprocessDownloadGateway,
)

pytestmark = pytest.mark.integration


def test_subprocess_gateway_reads_typed_events(tmp_path):
    worker = Path(__file__).parent / "fixtures" / "fake_worker.py"
    gateway = SubprocessDownloadGateway([sys.executable, str(worker)])
    request = DownloadRequest(
        lessons=(SelectedLesson("Курс", Lesson("Урок", "https://example.com")),),
        quality=VideoQuality.AUTO,
        save_path=tmp_path,
    )
    events = []
    summary = gateway.run(request, events.append)
    assert summary.total == 1
    assert summary.downloaded == 0
    assert summary.failed == ("Урок",)
    assert [event.type for event in events] == [
        DownloadEventType.LESSON_FAILED,
        DownloadEventType.SUMMARY,
    ]
