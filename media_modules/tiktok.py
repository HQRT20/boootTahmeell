import logging
import os
from typing import List, Tuple

import requests
from media_modules._utils import UA, download_file, download_with_ytdlp, DOWNLOADS_DIR

log = logging.getLogger("downloader.tiktok")


def download_tiktok(url: str) -> Tuple[List[str], str]:
    files, title = _download_tikwm_images(url)
    if files:
        return files, title
    return download_with_ytdlp(url, for_images=False)


def _download_tikwm_images(url: str) -> Tuple[List[str], str]:
    try:
        r = requests.post(
            "https://www.tikwm.com/api/",
            data={"url": url, "count": 12, "cursor": 0},
            headers={"User-Agent": UA},
            timeout=30,
        )
        if r.status_code != 200:
            return [], ""
        data = r.json()
        if data.get("code") != 0 or not data.get("data"):
            return [], ""

        info = data["data"]
        title = (info.get("title") or "")[:100]

        images = info.get("images") or []
        if images:
            files = []
            for i, img_url in enumerate(images[:10]):
                if isinstance(img_url, str):
                    f = download_file(img_url, f"tt_img_{i}", "jpg",
                                      referer="https://www.tiktok.com/")
                    if f:
                        files.append(f)
            if files:
                return files, title or "TikTok Slideshow"

    except Exception as e:
        log.debug("tikwm images failed: %s", e)
    return [], ""
