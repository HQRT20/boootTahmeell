import os
import logging
from typing import List, Tuple

from media_modules._utils import download_with_ytdlp
from media_modules.cobalt import (
    download_tikwm, download_twitter_api, download_instagram_api,
    download_pinterest_api, download_facebook_api,
)
from media_modules import (
    download_youtube, download_tiktok, download_facebook,
    download_twitter, download_instagram, download_pinterest,
)

log = logging.getLogger("downloader")


def _try_api_first(url: str) -> Tuple[List[str], str]:
    """Try direct API downloaders based on URL domain."""
    url_lower = url.lower()

    if any(d in url_lower for d in ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com")):
        files, title = download_tikwm(url)
        if files:
            return files, title

    if any(d in url_lower for d in ("x.com", "twitter.com")):
        files, title = download_twitter_api(url)
        if files:
            return files, title

    if any(d in url_lower for d in ("instagram.com", "instagr.am")):
        files, title = download_instagram_api(url)
        if files:
            return files, title

    if any(d in url_lower for d in ("pinterest.com", "pin.it")):
        files, title = download_pinterest_api(url)
        if files:
            return files, title

    if any(d in url_lower for d in ("facebook.com", "fb.watch", "fb.com")):
        files, title = download_facebook_api(url)
        if files:
            return files, title

    return [], ""


def _try_platform_fallback(url: str) -> Tuple[List[str], str]:
    """Try per-platform yt-dlp downloaders as second fallback."""
    url_lower = url.lower()

    try:
        if any(d in url_lower for d in ("tiktok.com", "vt.tiktok.com")):
            return download_tiktok(url)
        if any(d in url_lower for d in ("x.com", "twitter.com")):
            return download_twitter(url)
        if any(d in url_lower for d in ("instagram.com", "instagr.am")):
            return download_instagram(url)
        if any(d in url_lower for d in ("pinterest.com", "pin.it")):
            return download_pinterest(url)
        if any(d in url_lower for d in ("facebook.com", "fb.watch")):
            return download_facebook(url)
        if any(d in url_lower for d in ("youtube.com", "youtu.be")):
            return download_youtube(url)
    except Exception as e:
        log.debug("platform fallback failed for %s: %s", url[:60], e)

    return [], ""


def download_media(url: str) -> Tuple[List[str], str]:
    os.makedirs("downloads", exist_ok=True)

    # 1. Try direct APIs (tikwm, fxtwitter, instagram scrape, etc.)
    log.info("download_media start: %s", url[:80])
    try:
        files, title = _try_api_first(url)
        if files:
            log.info("API download succeeded for %s: %d files", url[:60], len(files))
            return files, title
    except Exception as e:
        log.warning("API download failed for %s: %s", url[:60], e)

    # 2. Try per-platform yt-dlp (youtube, tiktok, instagram playwright, etc.)
    try:
        files, title = _try_platform_fallback(url)
        if files:
            log.info("Platform fallback succeeded for %s: %d files", url[:60], len(files))
            return files, title
    except Exception as e:
        log.warning("Platform fallback failed for %s: %s", url[:60], e)

    # 3. Try generic yt-dlp (works for 1000+ sites)
    log.info("Falling back to generic yt-dlp for %s", url[:60])
    try:
        files, title = download_with_ytdlp(url)
        if files:
            return files, title or "Media"
    except Exception as e:
        log.exception("yt-dlp failed for %s: %s", url[:60], e)

    log.warning("All download methods failed for %s", url[:80])
    return [], ""
