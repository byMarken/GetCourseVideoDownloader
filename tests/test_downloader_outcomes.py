import asyncio
from pathlib import Path

import pytest

from getcourse_downloader.domain.events import DownloadEventType
from getcourse_downloader.domain.models import DownloadRequest, Lesson, SelectedLesson, VideoQuality
from getcourse_downloader.infrastructure.getcourse import downloader as downloader_module
from getcourse_downloader.infrastructure.getcourse.downloader import (
    PlaywrightDownloadGateway,
    _Playlist,
)
from getcourse_downloader.infrastructure.media.hls import HlsDownloadResult, HlsDownloadStatus


class _Page:
    def __init__(self, *, player: bool, playlist: tuple[str, str] | None = None) -> None:
        self.url = "about:blank"
        self._player = player
        self._playlist = playlist
        self._handlers = []

    def on(self, event, handler):
        if event == "response":
            self._handlers.append(handler)

    async def goto(self, url, **_):
        self.url = url
        if self._playlist:
            playlist_url, text = self._playlist

            class Response:
                url = playlist_url

                async def text(self):
                    return text

            for handler in self._handlers:
                handler(Response())

    async def query_selector(self, _):
        return object() if self._player else None

    async def wait_for_load_state(self, *_, **__):
        return None

    async def wait_for_timeout(self, *_):
        return None

    async def close(self):
        return None

    async def set_viewport_size(self, viewport):
        assert viewport == {"width": 1920, "height": 1080}


class _Browser:
    def __init__(self, page):
        self.page = page

    async def new_page(self, **_):
        return self.page


class _Hls:
    async def download(self, *_, **__):
        raise AssertionError("HLS downloader should not be called")


class _SuccessfulHls:
    def __init__(self) -> None:
        self.calls = 0

    async def download(self, _playlist_url, output_stem, *_args, **_kwargs):
        self.calls += 1
        return HlsDownloadResult(
            HlsDownloadStatus.DOWNLOADED,
            output_path=Path(f"{output_stem}.mp4"),
        )


def _item():
    return SelectedLesson(("Course", "Module"), Lesson("Lesson", "https://school/lesson/1"))


class _DelayedPlayerPage(_Page):
    def __init__(self) -> None:
        super().__init__(player=False)
        self._player_checks = 0

    async def query_selector(self, _):
        self._player_checks += 1
        return object() if self._player_checks > 1 else None


def test_no_player_and_no_hls_is_no_video(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader_module, "PLAYLIST_WAIT_SECONDS", 0.0)
    gateway = PlaywrightDownloadGateway(None, _Hls())  # type: ignore[arg-type]
    result = asyncio.run(
        gateway._download_lesson(
            _Browser(_Page(player=False)),
            _item(),
            tmp_path / "Lesson",
            "auto",
            lambda _: None,
        )
    )
    assert result.status.value == "no_video"


def test_player_without_hls_is_technical_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader_module, "PLAYLIST_WAIT_SECONDS", 0.0)
    gateway = PlaywrightDownloadGateway(None, _Hls())  # type: ignore[arg-type]
    events = []
    result = asyncio.run(
        gateway._download_lesson(
            _Browser(_Page(player=True)),
            _item(),
            tmp_path / "Lesson",
            "auto",
            events.append,
        )
    )
    assert result.status.value == "failed"
    assert events[-1].type is DownloadEventType.ERROR
    assert events[-1].lesson_url == "https://school/lesson/1"


def test_player_inserted_during_settle_is_not_reported_as_no_video(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader_module, "PLAYLIST_WAIT_SECONDS", 0.0)
    gateway = PlaywrightDownloadGateway(None, _Hls())  # type: ignore[arg-type]
    events = []

    result = asyncio.run(
        gateway._download_lesson(
            _Browser(_DelayedPlayerPage()),
            _item(),
            tmp_path / "Lesson",
            "auto",
            events.append,
        )
    )

    assert result.status.value == "failed"
    assert events[-1].type is DownloadEventType.ERROR


def test_lesson_finishes_without_post_download_five_second_idle(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader_module, "PLAYLIST_WAIT_SECONDS", 1.0)
    monkeypatch.setattr(downloader_module, "PLAYLIST_QUIET_SECONDS", 0.0)
    hls = _SuccessfulHls()
    gateway = PlaywrightDownloadGateway(None, hls)  # type: ignore[arg-type]
    page = _Page(
        player=True,
        playlist=(
            "https://cdn.example/video.m3u8",
            "#EXTM3U\n#EXTINF:5,\nsegment.ts\n",
        ),
    )

    async def download():
        return await asyncio.wait_for(
            gateway._download_lesson(
                _Browser(page),
                _item(),
                tmp_path / "Lesson",
                "auto",
                lambda _: None,
            ),
            timeout=0.75,
        )

    result = asyncio.run(download())

    assert result.status.value == "downloaded"
    assert hls.calls == 1


def test_master_and_captured_variant_are_deduplicated_by_canonical_url():
    master = _Playlist(
        "https://cdn.example/master.m3u8?token=one",
        "#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080\nvideo.m3u8?token=one\n",
    )
    variant = _Playlist(
        "https://cdn.example/video.m3u8?token=two",
        "#EXTM3U\n#EXTINF:5,\nsegment.ts\n",
    )

    selected = PlaywrightDownloadGateway._select_playlist_urls((master, variant), "auto")

    assert len(selected) == 1
    assert selected[0] == "https://cdn.example/video.m3u8?token=one"


def test_multiple_video_order_is_stable_despite_response_order():
    first = _Playlist("https://cdn.example/z.m3u8", "#EXTM3U\n#EXTINF:5,\nz.ts\n")
    second = _Playlist("https://cdn.example/a.m3u8", "#EXTM3U\n#EXTINF:5,\na.ts\n")

    assert PlaywrightDownloadGateway._select_playlist_urls((first, second), "auto") == [
        "https://cdn.example/a.m3u8",
        "https://cdn.example/z.m3u8",
    ]
    assert PlaywrightDownloadGateway._select_playlist_urls((second, first), "auto") == [
        "https://cdn.example/a.m3u8",
        "https://cdn.example/z.m3u8",
    ]


def test_direct_getcourse_variants_select_only_requested_quality():
    def playlist(quality: int) -> _Playlist:
        return _Playlist(
            f"https://api1.gcvh.ru/api/playlist/media/video/token/{quality}?jwt=x",
            "#EXTM3U\n#EXTINF:5,\nsegment.ts\n",
        )

    selected = PlaywrightDownloadGateway._select_playlist_urls(
        (playlist(360), playlist(720), playlist(1080)),
        "1080",
    )

    assert selected == ["https://api1.gcvh.ru/api/playlist/media/video/token/1080?jwt=x"]


def test_master_and_direct_variant_of_same_video_choose_only_highest():
    master = _Playlist(
        "https://api3.gcvh.ru/api/playlist/master/video/token",
        "#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080\n"
        "https://api1.gcvh.ru/api/playlist/media/video/token/1080?cdn=gcore\n",
    )
    direct_720 = _Playlist(
        "https://api1.gcvh.ru/api/playlist/media/video/token/720?cdn=proxy",
        "#EXTM3U\n#EXTINF:5,\nsegment.ts\n",
    )

    assert PlaywrightDownloadGateway._select_playlist_urls((master, direct_720), "auto") == [
        "https://api1.gcvh.ru/api/playlist/media/video/token/1080?cdn=gcore"
    ]


def test_text_lesson_is_saved_as_html(monkeypatch, tmp_path):
    class TextPage(_Page):
        async def content(self):
            return "<html><head></head><body><h1>Контрольная работа</h1></body></html>"

    monkeypatch.setattr(downloader_module, "PLAYLIST_WAIT_SECONDS", 0.0)
    gateway = PlaywrightDownloadGateway(None, _Hls())  # type: ignore[arg-type]
    stem = tmp_path / "Course" / "Контрольная работа"

    result = asyncio.run(
        gateway._download_lesson(
            _Browser(TextPage(player=False)),
            _item(),
            stem,
            "auto",
            lambda _: None,
        )
    )

    assert result.status.value == "downloaded"
    assert result.media[0].path == stem.with_suffix(".html")
    assert '<base href="https://school/lesson/1">' in stem.with_suffix(".html").read_text(
        encoding="utf-8"
    )


def test_output_stems_preserve_hierarchy_and_hash_all_collisions(tmp_path):
    lessons = (
        SelectedLesson(("Course", "Module"), Lesson("A:B", "https://school/lesson/1")),
        SelectedLesson(("Course", "Module"), Lesson("A?B", "https://school/lesson/2")),
        SelectedLesson(("Course", "Other"), Lesson("A:B", "https://school/lesson/3")),
    )
    request = DownloadRequest(lessons, VideoQuality.AUTO, tmp_path)
    stems = PlaywrightDownloadGateway._output_stems(request)
    assert stems[0].parent == tmp_path / "Course" / "Module"
    assert stems[1].parent == tmp_path / "Course" / "Module"
    assert stems[0].name.startswith("A_B~")
    assert stems[1].name.startswith("A_B~")
    assert stems[0] != stems[1]
    assert stems[2] == tmp_path / "Course" / "Other" / "A_B"


def test_output_stems_disambiguate_sanitized_folder_collisions_stably(tmp_path):
    lessons = (
        SelectedLesson(("A:B",), Lesson("First", "https://school/lesson/1")),
        SelectedLesson(("A?B",), Lesson("Second", "https://school/lesson/2")),
    )
    request = DownloadRequest(lessons, VideoQuality.AUTO, tmp_path)

    stems = PlaywrightDownloadGateway._output_stems(request)
    reversed_stems = PlaywrightDownloadGateway._output_stems(
        DownloadRequest(tuple(reversed(lessons)), VideoQuality.AUTO, tmp_path)
    )

    by_url = {item.lesson.url: stem for item, stem in zip(lessons, stems, strict=True)}
    reversed_by_url = {
        item.lesson.url: stem for item, stem in zip(reversed(lessons), reversed_stems, strict=True)
    }
    assert by_url == reversed_by_url
    assert stems[0].parent != stems[1].parent
    assert stems[0].parent.name.startswith("A_B~")
    assert stems[1].parent.name.startswith("A_B~")


def test_existing_output_is_detected_before_opening_lesson(tmp_path):
    stem = tmp_path / "Course" / "Lesson"
    stem.parent.mkdir()
    (stem.parent / "Lesson.mp4").write_bytes(b"done")
    assert PlaywrightDownloadGateway._output_exists(stem)

    (stem.parent / "Lesson.mp4").write_bytes(b"")
    assert not PlaywrightDownloadGateway._output_exists(stem)

    stem.mkdir()
    (stem / "video_1.mp4").write_bytes(b"one")
    (stem / "video_2.mp4").write_bytes(b"two")
    assert not PlaywrightDownloadGateway._output_exists(stem)


def test_path_too_long_is_rejected(tmp_path):
    from getcourse_downloader.infrastructure.storage.filenames import safe_lesson_output_stem

    with pytest.raises(ValueError, match="слишком длинный"):
        safe_lesson_output_stem(Path("C:/") / ("x" * 190), ("Course",), "Lesson")
