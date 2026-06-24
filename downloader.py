import os
import logging
from typing import List, Tuple

from media_modules import download_tiktok, download_instagram, download_pinterest
from media_modules.youtube import download_youtube

log = logging.getLogger("downloader")


def download_media(url: str) -> Tuple[List[str], str]:
    os.makedirs("downloads", exist_ok=True)
    log.info("download_media: %s", url[:80])

    url_lower = url.lower()

    for platform, domains, handler in [
        ("instagram", ("instagram.com", "instagr.am"), download_instagram),
        ("tiktok", ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com"), download_tiktok),
        ("youtube", ("youtube.com", "youtu.be"), download_youtube),
        ("pinterest", ("pinterest.com", "pin.it"), download_pinterest),
    ]:
        if any(d in url_lower for d in domains):
            try:
                files, title = handler(url)
                if files:
                    log.info("%s done: %d files", platform, len(files))
                    return files, title
            except Exception as e:
                log.warning("%s failed: %s", platform, e)

    log.warning("No handler matched for %s", url[:80])
    return [], ""
