from urllib.parse import urlsplit

PLAYLIST_PATH = "/api/playlist/"
VIDEO_PLAYER_SELECTOR = ", ".join(
    (
        "iframe.vhi-iframe",
        "iframe.js--vhi-iframe",
        "iframe[src*='rutube.ru/play/embed/']",
        "div.vhi-root",
        "div[data-video-hash]",
        ".vjs-big-play-button",
    )
)


def is_hls_playlist_url(url: str) -> bool:
    normalized = url.casefold()
    return PLAYLIST_PATH in normalized or urlsplit(normalized).path.endswith(".m3u8")


def is_master_playlist_url(url: str) -> bool:
    return is_hls_playlist_url(url)
