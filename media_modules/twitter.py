import re
import logging
from typing import List, Tuple, Optional

import requests
from media_modules._utils import UA, download_file, download_url, download_with_ytdlp, get_requests_cookies, get_playwright_cookies, find_brave_exe

log = logging.getLogger("downloader.twitter")
SYNDICATION_TOKEN = '4c2mmul6mnh'

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def download_twitter(url: str) -> Tuple[List[str], str]:
    handle, twitter_id = _extract_twitter_id(url)
    if not twitter_id:
        return download_with_ytdlp(url)

    files, title = _try_fxtwitter(twitter_id, handle)
    if files:
        return files, title

    files, title = _try_syndication(twitter_id)
    if files:
        return files, title

    files, title = download_with_ytdlp(url)
    if files:
        return files, title or "Twitter Media"

    return _playwright_twitter(url)


def _extract_twitter_id(url: str) -> Tuple[Optional[str], Optional[str]]:
    m = re.search(r'(?:x|twitter)\.com/i/(?:web/)?status/(\d+)', url)
    if m:
        return None, m.group(1)
    m = re.search(r'(?:x|twitter)\.com/([^/?#]+)/status(?:es)?/(\d+)', url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _try_fxtwitter(twitter_id: str, handle: Optional[str] = None) -> Tuple[List[str], str]:
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


def _try_syndication(twitter_id: str) -> Tuple[List[str], str]:
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


def _playwright_twitter(url: str) -> Tuple[List[str], str]:
    if not PLAYWRIGHT_AVAILABLE:
        return [], ""
    title = "Twitter Media"
    try:
        with sync_playwright() as p:
            launch_args = {'headless': True, 'args': ['--disable-blink-features=Automation', '--no-sandbox']}
            brave = find_brave_exe()
            browser = None
            if brave:
                try:
                    browser = p.chromium.launch(executable_path=brave, **launch_args)
                except Exception:
                    pass
            if not browser:
                for channel in ('chrome', 'msedge', 'chromium'):
                    try:
                        browser = p.chromium.launch(channel=channel, **launch_args)
                        break
                    except Exception:
                        continue
            if not browser:
                return [], ""
            context = None
            try:
                context = browser.new_context(viewport={'width': 1280, 'height': 900}, user_agent=UA)
                pw_cookies = get_playwright_cookies()
                if pw_cookies:
                    context.add_cookies(pw_cookies)
                page = context.new_page()
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(3500)
                media_urls = []
                for el in page.query_selector_all('img[src*="pbs.twimg.com/media"], video[src*="video.twimg.com"]'):
                    src = el.get_attribute('src')
                    if src:
                        media_urls.append(src)
                for el in page.query_selector_all('video source[src]'):
                    src = el.get_attribute('src')
                    if src:
                        media_urls.append(src)
                content = page.content()
                media_urls += re.findall(r'https://pbs\.twimg\.com/media/[A-Za-z0-9_\-]+\?[^"\'\s]+', content)
                media_urls += re.findall(r'https://video\.twimg\.com/[^"\'\s]+\.mp4[^"\'\s]*', content)
                try:
                    title = (page.title() or title).split(' / ')[0][:100]
                except Exception:
                    pass
                cookies = get_requests_cookies()
                files: List[str] = []
                seen = set()
                for mu in media_urls:
                    key = mu.split('?')[0]
                    if key in seen:
                        continue
                    seen.add(key)
                    f = download_url(mu, "tw_pw", cookies=cookies, referer="https://twitter.com/")
                    if f:
                        files.append(f)
                    if len(files) >= 10:
                        break
                return files, title
            finally:
                try:
                    if context:
                        context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        log.debug("playwright twitter failed: %s", e)
    return [], ""
