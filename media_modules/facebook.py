import logging
from typing import List, Tuple

from media_modules._utils import download_with_ytdlp

log = logging.getLogger("downloader.facebook")

def download_facebook(url: str) -> Tuple[List[str], str]:
    files, title = download_with_ytdlp(url, for_images=False)
    if files:
        return files, title or "Facebook Media"
    files, title = download_with_ytdlp(url, for_images=True)
    return files, title or "Facebook Media"
