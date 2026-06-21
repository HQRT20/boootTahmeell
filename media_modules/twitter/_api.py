import logging
from typing import List, Tuple, Optional

import requests
from media_modules._utils import UA, get_requests_cookies, download_url

log = logging.getLogger("downloader.twitter.api")
SYNDICATION_TOKEN = '4c2mmul6mnh'

def _best_video_variant(variants: list) -> Optional[str]:
    if not variants:
        return None
    mp4s = [v for v in variants if (v.get('content_type') or v.get('type') or '').endswith('mp4')]
    mp4s.sort(key=lambda v: v.get('bitrate') or v.get('bit_rate') or 0, reverse=True)
    if mp4s:
        return mp4s[0].get('url') or mp4s[0].get('src')
    for v in variants:
        if v.get('url'):
            return v['url']
    return None

def _collect_media_from_tweet(data: dict) -> List[str]:
    urls: List[str] = []
    if not isinstance(data, dict):
        return urls

    for m in (data.get('mediaDetails') or []):
        if m.get('type') in ('video', 'animated_gif'):
            u = _best_video_variant((m.get('video_info') or {}).get('variants') or [])
            if u:
                urls.append(u)
                continue
        photo = m.get('media_url_https') or m.get('media_url')
        if photo:
            urls.append(photo + '?name=orig')

    for key in ('media_extended', 'mediaURLs'):
        items = data.get(key)
        if isinstance(items, list):
            for m in items:
                if isinstance(m, str):
                    urls.append(m)
                elif isinstance(m, dict):
                    u = m.get('url') or m.get('thumbnail_url')
                    if u:
                        urls.append(u)

    tw = data.get('tweet') if isinstance(data.get('tweet'), dict) else data
    media = (tw or {}).get('media') if isinstance(tw, dict) else None
    if isinstance(media, dict):
        for v in (media.get('videos') or []):
            u = v.get('url') or (v.get('variants') or [{}])[0].get('url')
            if u:
                urls.append(u)
        for p in (media.get('photos') or []):
            u = p.get('url')
            if u:
                urls.append(u)

    return list(dict.fromkeys(urls))

def _extract_title(data: dict) -> str:
    tw = data.get('tweet') if isinstance(data.get('tweet'), dict) else data
    if isinstance(tw, dict):
        txt = tw.get('text') or tw.get('full_text') or data.get('text') or ""
        if txt:
            return txt.strip().split('\n')[0][:100]
    txt = data.get('text') or ""
    return txt.strip().split('\n')[0][:100] if txt else "Twitter Media"

def try_fxtwitter(twitter_id: str, handle: Optional[str] = None) -> Tuple[List[str], str]:
    bases = [
        f"https://api.fxtwitter.com/status/{twitter_id}",
        f"https://api.vxtwitter.com/Twitter/status/{twitter_id}",
    ]
    if handle:
        bases.insert(0, f"https://api.fxtwitter.com/{handle}/status/{twitter_id}")

    for api in bases:
        try:
            r = requests.get(api, headers={'User-Agent': UA, 'Accept': 'application/json'}, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            media_urls = _collect_media_from_tweet(data)
            if not media_urls:
                continue
            title = _extract_title(data)
            cookies = get_requests_cookies()
            files: List[str] = []
            for u in media_urls[:10]:
                f = download_url(u, "tw_fx", cookies=cookies, referer="https://twitter.com/")
                if f:
                    files.append(f)
            if files:
                return files, title
        except Exception as e:
            log.debug("fxtwitter failed for %s: %s", api, e)
    return [], ""

def try_syndication(twitter_id: str) -> Tuple[List[str], str]:
    try:
        r = requests.get(
            "https://cdn.syndication.twimg.com/tweet-result",
            params={'id': twitter_id, 'token': SYNDICATION_TOKEN, 'lang': 'en'},
            headers={'User-Agent': UA, 'Accept': 'application/json'},
            timeout=15,
        )
        if r.status_code != 200:
            return [], ""
        data = r.json()
        media_urls = _collect_media_from_tweet(data)
        if not media_urls:
            return [], ""
        title = _extract_title(data)
        cookies = get_requests_cookies()
        files: List[str] = []
        for u in media_urls[:10]:
            f = download_url(u, "tw_syn", cookies=cookies, referer="https://twitter.com/")
            if f:
                files.append(f)
        if files:
            return files, title
    except Exception as e:
        log.debug("syndication failed: %s", e)
    return [], ""
