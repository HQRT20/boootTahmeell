import re
import json
import logging
from typing import List, Tuple

import requests
from media_modules._utils import UA, download_with_ytdlp, download_url

log = logging.getLogger("downloader.pinterest")

def _try_api_extract(url: str) -> Tuple[List[str], str]:
    try:
        r = requests.get(url, headers={'User-Agent': UA}, allow_redirects=True, timeout=20)
        json_data = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>({.*?})</script>', r.text, re.DOTALL)
        if not json_data:
            json_data = re.search(r'<script[^>]*id="__PWS_DATA__"[^>]*>({.*?})</script>', r.text, re.DOTALL)
        if not json_data:
            return [], ""

        data = json.loads(json_data.group(1))
        urls: List[str] = []
        text = ""
        for match_val in re.finditer(r'https://[^"\']*pinimg[^"\']*originals[^"\']+\.(?:jpg|jpeg|png|webp|gif|mp4)', json.dumps(data)):
            u = match_val.group(0).replace('\\u002F', '/').replace('\\/', '/')
            if u not in urls:
                urls.append(u)
        for match_val in re.finditer(r'"title":"([^"]+)"', r.text):
            text = match_val.group(1)[:100]
            break
        if not text:
            m = re.search(r'<title>([^<]+)', r.text)
            if m:
                text = m.group(1).split('|')[0].strip()[:100]

        files: List[str] = []
        for u in urls[:10]:
            if "d53b014d86a6b6761bf649a0ed813c2b" in u:
                continue
            f = download_url(u, "pin")
            if f:
                files.append(f)
        return files, text or "Pinterest Media"
    except Exception as e:
        log.debug("pinterest api extract failed: %s", e)
    return [], ""

def download_pinterest(url: str) -> Tuple[List[str], str]:
    files, title = _try_api_extract(url)
    if files:
        return files, title
    files, title = download_with_ytdlp(url, for_images=False)
    if files:
        return files, title or "Pinterest Media"
    files, title = download_with_ytdlp(url, for_images=True)
    return files, title or "Pinterest Media"
