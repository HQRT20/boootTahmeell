import logging
from typing import Tuple, List, Optional

from media_modules._utils import download_with_ytdlp, UA
from media_modules.twitter._api import try_fxtwitter, try_syndication
from media_modules.twitter._playwright import playwright_twitter

log = logging.getLogger("downloader.twitter")

def _extract_twitter_id(url: str) -> Tuple[Optional[str], Optional[str]]:
    import re
    m = re.search(r'(?:x|twitter)\.com/i/(?:web/)?status/(\d+)', url)
    if m:
        return None, m.group(1)
    m = re.search(r'(?:x|twitter)\.com/([^/?#]+)/status(?:es)?/(\d+)', url)
    if m:
        return m.group(1), m.group(2)
    return None, None

def download_twitter(url: str) -> Tuple[List[str], str]:
    handle, twitter_id = _extract_twitter_id(url)
    if not twitter_id:
        files, title = download_with_ytdlp(url)
        return files, title or "Twitter Media"

    files, title = try_fxtwitter(twitter_id, handle)
    if files:
        return files, title

    files, title = try_syndication(twitter_id)
    if files:
        return files, title

    files, title = download_with_ytdlp(url)
    if files:
        return files, title or "Twitter Media"

    return playwright_twitter(url)
