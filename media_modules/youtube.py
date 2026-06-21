import logging
from typing import List, Tuple

from media_modules._utils import download_with_ytdlp

log = logging.getLogger("downloader.youtube")

def download_youtube(url: str) -> Tuple[List[str], str]:
    files, title = download_with_ytdlp(url, for_images=False)
    return files, title or "YouTube Media"
