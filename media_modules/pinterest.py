import re
import logging
from typing import List, Tuple

import requests
from media_modules._utils import UA, download_file, download_with_ytdlp

log = logging.getLogger("downloader.pinterest")


def _resolve_short_url(url: str) -> str:
    if "pin.it/" not in url:
        return url
    try:
        r = requests.get(url, headers={"User-Agent": UA}, allow_redirects=True, timeout=15)
        if r.status_code == 200:
            resolved = r.url
            log.info("Resolved %s -> %s", url, resolved)
            return resolved
    except Exception as e:
        log.debug("Failed to resolve short URL: %s", e)
    return url


def download_pinterest(url: str) -> Tuple[List[str], str]:
    resolved = _resolve_short_url(url)

    files, title = download_with_ytdlp(resolved, for_images=False)
    if files:
        return files, title or "Pinterest Video"

    files, title = _try_scrape(resolved)
    return files, title


def _try_scrape(url: str) -> Tuple[List[str], str]:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, allow_redirects=True, timeout=20)
        if r.status_code != 200:
            return [], ""
        text = r.text

        title = ""
        m = re.search(r"<title>([^<]+)", text)
        if m:
            title = m.group(1).split("|")[0].strip()[:100]

        vid_m = re.search(
            r'https://v1\.pinimg\.com/videos/[^\s"\'<>]+\.mp4', text
        )
        if vid_m:
            vid_url = vid_m.group(0).split('"')[0].split("'")[0].split("<")[0]
            f = download_file(vid_url, "pin_vid", "mp4", referer="https://www.pinterest.com/")
            if f:
                return [f], title or "Pinterest Video"

        vid_m2 = re.search(
            r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:video"', text
        )
        if vid_m2:
            f = download_file(vid_m2.group(1), "pin_vid", "mp4", referer="https://www.pinterest.com/")
            if f:
                return [f], title or "Pinterest Video"

        img_m = re.search(
            r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:image"', text
        )
        if img_m:
            img_url = re.sub(r"/\d+x\d+/", "/originals/", img_m.group(1))
            f = download_file(img_url, "pin_img", "jpg", referer="https://www.pinterest.com/")
            if f:
                return [f], title or "Pinterest Image"

        urls = []
        for match in re.finditer(r"https://i\.pinimg\.com/originals/[^\s\"'<>]+", text):
            u = match.group(0).split('"')[0].split("'")[0].split("<")[0]
            if u not in urls:
                urls.append(u)

        if not urls:
            for match in re.finditer(r"https://i\.pinimg\.com/\d+x\d+/[^\s\"'<>]+", text):
                u = match.group(0).split('"')[0].split("'")[0].split("<")[0]
                if u not in urls and "75x75" not in u:
                    urls.append(u)

        files = []
        for u in urls[:1]:
            f = download_file(u, "pin_img", "jpg", referer="https://www.pinterest.com/")
            if f:
                files.append(f)
        if files:
            return files, title or "Pinterest Image"

    except Exception as e:
        log.debug("pinterest scrape failed: %s", e)
    return [], ""
