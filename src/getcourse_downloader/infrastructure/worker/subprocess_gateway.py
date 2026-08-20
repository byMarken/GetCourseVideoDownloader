from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
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
        self._command_file: Path | None = None
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._done.set()

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
        self._done.clear()
        request_file: Path | None = None
        event_file: Path | None = None
        command_file: Path | None = None
        summary: DownloadSummary | None = None
        failed_titles: list[str] = []
        request_descriptor, request_name = tempfile.mkstemp(prefix="gcd-request-", suffix=".json")
        event_descriptor, event_name = tempfile.mkstemp(prefix="gcd-events-", suffix=".jsonl")
        command_descriptor, command_name = tempfile.mkstemp(prefix="gcd-commands-", suffix=".jsonl")
        request_file = Path(request_name)
        event_file = Path(event_name)
        command_file = Path(command_name)
        try:
            with os.fdopen(request_descriptor, "w", encoding="utf-8") as stream:
                json.dump(request.to_dict(), stream, ensure_ascii=False)
            os.close(event_descriptor)
            os.close(command_descriptor)

            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "utf-8"
            environment["PYTHONUTF8"] = "1"
            process = subprocess.Popen(
                [
                    *self._command(),
                    "--request-file",
                    str(request_file),
                    "--events-file",
                    str(event_file),
                    "--commands-file",
                    str(command_file),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                creationflags=flags,
                env=environment,
            )
            with self._lock:
                self._process = process
                self._command_file = command_file

            def consume(line: str) -> None:
                nonlocal summary
                try:
                    event = DownloadEvent.from_json(line)
                except InvalidDataError:
                    return
                on_event(event)
                if event.type is DownloadEventType.LESSON_FAILED and event.lesson:
                    failed_titles.append(event.lesson)
                if event.type is DownloadEventType.SUMMARY:
                    summary = DownloadSummary(
                        total=event.total or 0,
                        downloaded=event.downloaded or 0,
                        already_present=event.already_present or 0,
                        no_video=event.no_video or 0,
                        failed=tuple(failed_titles),
                        cancelled=event.cancelled or 0,
                    )

            with event_file.open("r", encoding="utf-8") as stream:
                while True:
                    raw_line = stream.readline()
                    if raw_line:
                        line = raw_line.strip()
                        if line:
                            consume(line)
                        continue
                    if process.poll() is not None:
                        for remaining in stream:
                            line = remaining.strip()
                            if line:
                                consume(line)
                        break
                    time.sleep(0.05)

            return_code = process.wait()
            if summary is None:
                raise DownloaderError(
                    f"Worker завершился без итогового события (код {return_code})"
                )
            return summary
        finally:
            with self._lock:
                self._process = None
                self._command_file = None
                self._done.set()
            if request_file:
                request_file.unlink(missing_ok=True)
            if event_file:
                event_file.unlink(missing_ok=True)
            if command_file:
                command_file.unlink(missing_ok=True)

    def _send_command(self, command: str) -> None:
        with self._lock:
            path = self._command_file
            process = self._process
            if path is None or process is None or process.poll() is not None:
                return
            try:
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"command": command}) + "\n")
                    stream.flush()
            except OSError:
                return

    def continue_authentication(self) -> None:
        self._send_command("continue_authentication")

    def cancel(self) -> None:
        self._send_command("cancel")

    def shutdown(self, timeout: float = 6.0) -> None:
        self.cancel()
        if self._done.wait(timeout):
            return
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        else:
            process.kill()
        self._done.wait(2)
