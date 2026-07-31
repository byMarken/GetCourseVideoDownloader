from app.services.givereq import (
    _extract_quality,
    _parse_master_playlist,
    _select_quality_url,
    sanitize_filename,
)


def test_sanitize_filename_removes_status_words():
    assert sanitize_filename("Урок 1 Просмотрено") == "Урок 1"
    assert sanitize_filename("Урок 2 Пройдено") == "Урок 2"
    assert sanitize_filename("Урок 3 Завершено") == "Урок 3"


def test_sanitize_filename_collapses_whitespace():
    assert sanitize_filename("Урок   с  пробелами") == "Урок с пробелами"


def test_sanitize_filename_replaces_illegal_chars():
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|') == "a_b_c_d_e_f_g_h_i_"


def test_extract_quality_from_url():
    assert _extract_quality("https://example.com/video/720/index.m3u8") == 720
    assert _extract_quality("https://example.com/video/1080/index.m3u8") == 1080
    assert _extract_quality("https://example.com/video/noquality/index.m3u8") == 0


MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
360/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720
720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080
1080/index.m3u8
"""


def test_parse_master_playlist_resolves_relative_urls():
    qualities = _parse_master_playlist(MASTER_PLAYLIST, "https://example.com/master.m3u8")
    assert qualities == {
        360: "https://example.com/360/index.m3u8",
        720: "https://example.com/720/index.m3u8",
        1080: "https://example.com/1080/index.m3u8",
    }


def test_parse_master_playlist_uses_resolution_fallback():
    playlist = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\nstream.m3u8\n"
    qualities = _parse_master_playlist(playlist, "https://example.com/master.m3u8")
    assert qualities == {720: "https://example.com/stream.m3u8"}


def test_select_quality_auto_picks_highest():
    qualities = {360: "a", 720: "b", 1080: "c"}
    assert _select_quality_url(qualities, "auto") == "c"


def test_select_quality_exact_match():
    qualities = {360: "a", 720: "b", 1080: "c"}
    assert _select_quality_url(qualities, "720") == "b"


def test_select_quality_falls_back_to_best_below():
    qualities = {360: "a", 720: "b"}
    assert _select_quality_url(qualities, "1080") == "b"


def test_select_quality_falls_back_to_lowest():
    qualities = {1080: "c"}
    assert _select_quality_url(qualities, "360") == "c"


def test_select_quality_empty():
    assert _select_quality_url({}, "720") is None


def test_extract_quality_ignores_query_string():
    assert _extract_quality("https://example.com/video/720/index.m3u8?token=abc") == 720


def test_extract_quality_ignores_query_numbers():
    assert _extract_quality("https://example.com/index.m3u8?quality=1080") == 0


def test_parse_master_playlist_absolute_urls():
    playlist = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\n"
        "https://cdn.example.com/720/index.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080\n"
        "https://cdn.example.com/1080/index.m3u8\n"
    )
    qualities = _parse_master_playlist(playlist, "https://example.com/master.m3u8")
    assert qualities == {
        720: "https://cdn.example.com/720/index.m3u8",
        1080: "https://cdn.example.com/1080/index.m3u8",
    }


def test_parse_master_playlist_uses_url_quality_without_resolution():
    playlist = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000000\n480/index.m3u8\n"
    qualities = _parse_master_playlist(playlist, "https://example.com/master.m3u8")
    assert qualities == {480: "https://example.com/480/index.m3u8"}


def test_parse_master_playlist_empty():
    assert _parse_master_playlist("", "https://example.com/master.m3u8") == {}
