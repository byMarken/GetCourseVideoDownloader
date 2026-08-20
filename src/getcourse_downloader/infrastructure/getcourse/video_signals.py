from urllib.parse import urlsplit

VIDEO_PLAYER_SELECTOR = ", ".join(
    (
        "iframe.vhi-iframe",
        "iframe.js--vhi-iframe",
        "iframe[src*='rutube.ru/play/embed/']",
        "div.vhi-root",
        "div[data-video-hash]",
    )
)


def is_hls_playlist_url(url: str) -> bool:
    normalized = url.casefold()
    path = urlsplit(normalized).path
    return "/api/playlist/" in path or path.endswith(".m3u8")


def is_master_playlist_url(url: str) -> bool:
    return is_hls_playlist_url(url)
