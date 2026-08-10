from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from getcourse_downloader.application.ports.download import EventHandler
from getcourse_downloader.domain.errors import DownloaderError, InvalidDataError
from getcourse_downloader.domain.events import DownloadEvent, DownloadEventType
from getcourse_downloader.domain.models import DownloadRequest, DownloadSummary


class SubprocessDownloadGateway:
    """Runs the downloader in an isolated process and consumes JSONL events."""

    def __init__(self, entrypoint: list[str] | None = None) -> None:
        self._entrypoint = entrypoint
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def _command(self) -> list[str]:
        if self._entrypoint:
            return list(self._entrypoint)
        if getattr(sys, "frozen", False):
            return [sys.executable, "--download-worker"]
        return [
            sys.executable,
            "-m",
            "getcourse_downloader.presentation.cli.worker",
        ]

    def run(self, request: DownloadRequest, on_event: EventHandler) -> DownloadSummary:
        request_file: Path | None = None
        summary: DownloadSummary | None = None
        failed_titles: list[str] = []
        descriptor, filename = tempfile.mkstemp(prefix="gcd-request-", suffix=".json")
        request_file = Path(filename)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(request.to_dict(), stream, ensure_ascii=False)

            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "utf-8"
            environment["PYTHONUTF8"] = "1"
            process = subprocess.Popen(
                [*self._command(), "--request-file", str(request_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
                env=environment,
            )
            with self._lock:
                self._process = process

            for raw_line in process.stdout or ():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = DownloadEvent.from_json(line)
                except InvalidDataError:
                    event = DownloadEvent(
                        DownloadEventType.LOG,
                        message=line,
                        stage="worker",
                        level="warning",
                    )
                on_event(event)
                if event.type is DownloadEventType.LESSON_FAILED and event.lesson:
                    failed_titles.append(event.lesson)
                if event.type is DownloadEventType.SUMMARY:
                    summary = DownloadSummary(
                        total=event.total or 0,
                        downloaded=event.current or 0,
                        failed=tuple(failed_titles),
                    )

            return_code = process.wait()
            if summary is None:
                if return_code == 0:
                    summary = DownloadSummary(
                        total=len(request.lessons),
                        downloaded=len(request.lessons),
                    )
                else:
                    raise DownloaderError(f"Worker завершился с кодом {return_code}")
            return summary
        finally:
            with self._lock:
                self._process = None
            if request_file:
                request_file.unlink(missing_ok=True)

    def continue_authentication(self) -> None:
        with self._lock:
            process = self._process
            if process and process.stdin:
                try:
                    process.stdin.write("\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    return

    def cancel(self) -> None:
        with self._lock:
            process = self._process
            if process and process.poll() is None:
                process.terminate()
