from getcourse_downloader.infrastructure.getcourse.video_signals import (
    VIDEO_PLAYER_SELECTOR,
    is_hls_playlist_url,
    is_master_playlist_url,
)


def test_video_selector_keeps_getcourse_and_adds_old_rutube_embed():
    assert "iframe.vhi-iframe" in VIDEO_PLAYER_SELECTOR
    assert "iframe.js--vhi-iframe" in VIDEO_PLAYER_SELECTOR
    assert "rutube.ru/play/embed/" in VIDEO_PLAYER_SELECTOR


def test_hls_url_detection_supports_getcourse_and_rutube_formats():
    assert is_hls_playlist_url("https://vh.example/api/playlist/master/123")
    assert is_hls_playlist_url("https://bl.rutube.ru/route/video/master.m3u8?token=abc")
    assert is_master_playlist_url("https://river.rutube.ru/video/index.m3u8")
    assert not is_hls_playlist_url("https://rutube.ru/play/embed/video/")
    assert not is_hls_playlist_url("https://example.com/poster.jpg")
