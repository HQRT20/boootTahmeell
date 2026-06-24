import os
import logging
from typing import List, Tuple

from media_modules._utils import download_with_ytdlp
from media_modules import (
    download_youtube, download_tiktok,
    download_instagram, download_pinterest,
)

log = logging.getLogger("downloader")


def download_media(url: str) -> Tuple[List[str], str]:
    os.makedirs("downloads", exist_ok=True)
    log.info("download_media start: %s", url[:80])

    url_lower = url.lower()

    if any(d in url_lower for d in ("instagram.com", "instagr.am")):
        try:
            files, title = download_instagram(url)
            if files:
                log.info("instagram done: %d files", len(files))
                return files, title
        except Exception as e:
            log.warning("instagram failed: %s", e)

    if any(d in url_lower for d in ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com")):
        try:
            files, title = download_tiktok(url)
            if files:
                log.info("tiktok done: %d files", len(files))
                return files, title
        except Exception as e:
            log.warning("tiktok failed: %s", e)

    if any(d in url_lower for d in ("youtube.com", "youtu.be")):
        try:
            files, title = download_youtube(url)
            if files:
                log.info("youtube done: %d files", len(files))
                return files, title
        except Exception as e:
            log.warning("youtube failed: %s", e)

    if any(d in url_lower for d in ("pinterest.com", "pin.it")):
        try:
            files, title = download_pinterest(url)
            if files:
                log.info("pinterest done: %d files", len(files))
                return files, title
        except Exception as e:
            log.warning("pinterest failed: %s", e)

    log.info("Falling back to generic yt-dlp for %s", url[:60])
    try:
        files, title = download_with_ytdlp(url)
        if files:
            return files, title or "Media"
    except Exception as e:
        log.exception("yt-dlp failed: %s", e)

    log.warning("All download methods failed for %s", url[:80])
    return [], ""
