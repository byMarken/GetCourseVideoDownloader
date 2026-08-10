MASTER_PLAYLIST_PATH = "/api/playlist/master/"
VIDEO_PLAYER_SELECTOR = "iframe.vhi-iframe, iframe.js--vhi-iframe"


def is_master_playlist_url(url: str) -> bool:
    return MASTER_PLAYLIST_PATH in url.casefold()
