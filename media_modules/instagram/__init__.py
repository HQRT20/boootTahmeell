import logging
from typing import List, Tuple

from media_modules._utils import download_with_ytdlp
from media_modules.instagram._playwright import playwright_instagram

log = logging.getLogger("downloader.instagram")

def download_instagram(url: str) -> Tuple[List[str], str]:
    is_reel = "/reel/" in url.lower()

    files, title = download_with_ytdlp(url, for_images=False)
    if files:
        return files, title or "Instagram Media"

    if not is_reel:
        files, title = download_with_ytdlp(url, for_images=True)
        if files:
            return files, title or "Instagram Media"

    return playwright_instagram(url)
