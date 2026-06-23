import re
import logging
from typing import List, Tuple

import requests
from media_modules._utils import UA, download_file, download_with_ytdlp

log = logging.getLogger("downloader.facebook")


def download_facebook(url: str) -> Tuple[List[str], str]:
    files, title = download_with_ytdlp(url, for_images=False, platform="facebook")
    if files:
        return files, title or "Facebook Media"

    files, title = _download_fbdown(url)
    if files:
        return files, title

    files, title = download_with_ytdlp(url, for_images=True, platform="facebook")
    return files, title


def _download_fbdown(url: str) -> Tuple[List[str], str]:
    try:
        r = requests.post(
            "https://fbdown.net/download.php",
            data={"URLz": url},
            headers={"User-Agent": UA, "Referer": "https://fbdown.net/"},
            timeout=30,
        )
        if r.status_code != 200:
            return [], ""
        title_m = re.search(r'<title>([^<]+)', r.text)
        title = title_m.group(1).strip()[:100] if title_m else ""
        video_urls = re.findall(r'(https?://[^"\']+\.mp4[^"\']*)', r.text)
        files = []
        for u in video_urls[:3]:
            f = download_file(u, "fb_vid", referer="https://fbdown.net/")
            if f:
                files.append(f)
        if files:
            return files, title or "Facebook Video"
    except Exception as e:
        log.debug("fbdown failed: %s", e)
    return [], ""
