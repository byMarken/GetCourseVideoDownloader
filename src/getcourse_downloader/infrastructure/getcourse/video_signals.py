from urllib.parse import urlsplit

MASTER_PLAYLIST_PATH = "/api/playlist/master/"
VIDEO_PLAYER_SELECTOR = ", ".join(
    (
        "iframe.vhi-iframe",
        "iframe.js--vhi-iframe",
        "iframe[src*='rutube.ru/play/embed/']",
    )
)


def is_hls_playlist_url(url: str) -> bool:
    normalized = url.casefold()
    return MASTER_PLAYLIST_PATH in normalized or urlsplit(normalized).path.endswith(".m3u8")


def is_master_playlist_url(url: str) -> bool:
    return is_hls_playlist_url(url)
