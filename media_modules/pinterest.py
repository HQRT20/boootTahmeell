import re
import json
import logging
from typing import List, Tuple

import requests
from media_modules._utils import UA, download_file, download_url, download_with_ytdlp

log = logging.getLogger("downloader.pinterest")


def download_pinterest(url: str) -> Tuple[List[str], str]:
    files, title = _try_scrape(url)
    if files:
        return files, title
    files, title = download_with_ytdlp(url, for_images=False)
    if files:
        return files, title or "Pinterest Media"
    return download_with_ytdlp(url, for_images=True)


def _try_scrape(url: str) -> Tuple[List[str], str]:
    try:
        r = requests.get(url, headers={'User-Agent': UA}, allow_redirects=True, timeout=20)
        if r.status_code != 200:
            return [], ""

        title = ""
        m = re.search(r'<title>([^<]+)', r.text)
        if m:
            title = m.group(1).split("|")[0].strip()[:100]

        video_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:video"', r.text)
        if video_m:
            f = download_file(video_m.group(1), "pin_vid", referer="https://www.pinterest.com/")
            if f:
                return [f], title or "Pinterest Video"

        img_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:image"', r.text)
        if img_m:
            img_url = re.sub(r'/\d+x\d+/', '/originals/', img_m.group(1))
            f = download_file(img_url, "pin_img", "jpg", referer="https://www.pinterest.com/")
            if f:
                return [f], title or "Pinterest Image"

        urls = []
        for match in re.finditer(r'https://i\.pinimg\.com/originals/[^\s"\'<>]+', r.text):
            u = match.group(0).split('"')[0].split("'")[0].split('<')[0]
            if u not in urls:
                urls.append(u)

        if not urls:
            for match in re.finditer(r'https://i\.pinimg\.com/\d+x\d+/[^\s"\'<>]+', r.text):
                u = match.group(0).split('"')[0].split("'")[0].split('<')[0]
                if u not in urls and "75x75" not in u:
                    urls.append(u)

        files = []
        for u in urls[:1]:
            f = download_url(u, "pin_img", referer="https://www.pinterest.com/")
            if f:
                files.append(f)
        if files:
            return files, title or "Pinterest Media"

    except Exception as e:
        log.debug("pinterest scrape failed: %s", e)
    return [], ""
