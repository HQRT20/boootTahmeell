import os
import re
import json
import logging
import urllib.parse
from typing import List, Tuple

import requests
from media_modules._utils import UA, download_file, fix_extension, download_with_ytdlp, download_url, get_requests_cookies

log = logging.getLogger("downloader.instagram")

_IG_COOKIES = {}

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def download_instagram(url: str) -> Tuple[List[str], str]:
    files, title = _download_ig_api(url)
    if files:
        return files, title
    files, title = download_with_ytdlp(url, for_images=False)
    if files:
        return files, title or "Instagram Media"
    files, title = download_with_ytdlp(url, for_images=True)
    if files:
        return files, title or "Instagram Media"
    return [], ""


def _load_ig_cookies():
    global _IG_COOKIES
    if _IG_COOKIES:
        return _IG_COOKIES
    cookie_str = os.environ.get("IG_COOKIES", "")
    if cookie_str:
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                _IG_COOKIES[k.strip()] = v.strip()
        log.info("ig cookies loaded: %d from env", len(_IG_COOKIES))
        return _IG_COOKIES
    for path in ("instagram_cookies.txt", "cookies.txt"):
        if os.path.exists(path):
            try:
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split("\t")
                        if len(parts) >= 7:
                            _IG_COOKIES[parts[5]] = parts[6]
                if _IG_COOKIES:
                    log.info("ig cookies loaded: %d from %s", len(_IG_COOKIES), path)
                    return _IG_COOKIES
            except Exception as e:
                log.debug("failed to load cookies from %s: %s", path, e)
    return _IG_COOKIES


def _get_ig_session(url):
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "X-IG-App-ID": "936619743392459",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    })
    cookies = _load_ig_cookies()
    if cookies:
        s.cookies.update(cookies)
    return s


def _shortcode_to_mediaid(shortcode):
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    media_id = 0
    for char in shortcode:
        media_id = media_id * 64 + alphabet.index(char)
    return str(media_id)


def _ig_parse_item(item):
    files, title, is_video = [], "", False
    caption = item.get("caption")
    if isinstance(caption, dict):
        title = (caption.get("text") or "")[:100]
    elif isinstance(caption, str):
        title = caption[:100]
    video_versions = item.get("video_versions") or []
    carousel = item.get("carousel_media") or []
    if video_versions and not carousel:
        best = max(video_versions, key=lambda v: v.get("width", 0) * v.get("height", 0))
        if best.get("url"):
            files.append(("video", best["url"]))
            is_video = True
    elif carousel:
        for ci in carousel:
            ci_vids = ci.get("video_versions") or []
            if ci_vids:
                best = max(ci_vids, key=lambda v: v.get("width", 0) * v.get("height", 0))
                if best.get("url"):
                    files.append(("video", best["url"]))
            else:
                imgs = (ci.get("image_versions2") or {}).get("candidates") or []
                if imgs:
                    best = max(imgs, key=lambda i: i.get("width", 0) * i.get("height", 0))
                    if best.get("url"):
                        files.append(("image", best["url"]))
    else:
        imgs = (item.get("image_versions2") or {}).get("candidates") or []
        if imgs:
            best = max(imgs, key=lambda i: i.get("width", 0) * i.get("height", 0))
            if best.get("url"):
                files.append(("image", best["url"]))
    return files, title, is_video


def _ig_download_media(media_urls, prefix="ig"):
    files = []
    for kind, murl in media_urls:
        ext = "mp4" if kind == "video" else "jpg"
        tag = f"{prefix}_{'vid' if kind == 'video' else 'img'}_{len(files)}"
        f = download_file(murl, tag, ext, referer="https://www.instagram.com/")
        if f:
            if kind == "image":
                f = fix_extension(f)
            files.append(f)
    return files


def _download_ig_api(url: str) -> Tuple[List[str], str]:
    try:
        clean_url = url.split("?")[0].rstrip("/")
        shortcode_match = re.search(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)', clean_url)
        if not shortcode_match:
            return [], ""
        sc = shortcode_match.group(1)
        img_index = 0
        idx_match = re.search(r'img_index=(\d+)', url)
        if idx_match:
            img_index = int(idx_match.group(1))
        log.info("ig download: shortcode=%s img_index=%d url=%s", sc, img_index, url[:80])
        session = _get_ig_session(clean_url)
        media_id = _shortcode_to_mediaid(sc)
        is_reel = "/reel/" in url.lower()

        try:
            api_url = f"https://i.instagram.com/api/v1/media/{media_id}/info/"
            headers = {
                "User-Agent": UA,
                "X-IG-App-ID": "936619743392459",
                "X-ASBD-ID": "198387",
                "X-Requested-With": "XMLHttpRequest",
            }
            if "csrftoken" in session.cookies:
                headers["X-CSRFToken"] = session.cookies["csrftoken"]
            r = session.get(api_url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                items = data.get("items") or []
                if items:
                    item = items[0]
                    media_urls, title, _ = _ig_parse_item(item)
                    has_video = any(k == "video" for k, _ in media_urls)
                    if has_video and is_reel:
                        log.info("ig api: video reel, skip for yt-dlp")
                        return [], ""
                    if media_urls:
                        if img_index > 0:
                            target = max(0, min(img_index - 1, len(media_urls) - 1))
                            media_urls = [media_urls[target]]
                        img_only = [(k, u) for k, u in media_urls if k == "image"]
                        if img_only:
                            log.info("ig api: found %d image items", len(img_only))
                            files = _ig_download_media(img_only, "ig_api")
                            if files:
                                return files, title or "Instagram Media"
        except Exception as e:
            log.debug("ig api failed: %s", e)

        try:
            variables = json.dumps({
                "shortcode": sc,
                "child_comment_count": 0,
                "fetch_comment_count": 0,
                "parent_comment_count": 0,
                "has_threaded_comments": False,
            })
            gql_url = f"https://www.instagram.com/graphql/query/?doc_id=8845758582119845&variables={urllib.parse.quote(variables)}"
            headers = {
                "User-Agent": UA,
                "X-IG-App-ID": "936619743392459",
                "X-Requested-With": "XMLHttpRequest",
            }
            if "csrftoken" in session.cookies:
                headers["X-CSRFToken"] = session.cookies["csrftoken"]
            r = session.get(gql_url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                media = data.get("data", {}).get("xdt_shortcode_media") or {}
                if media:
                    files = []
                    title = ""
                    caption_edges = media.get("edge_media_to_caption", {}).get("edges", [])
                    if caption_edges:
                        title = caption_edges[0].get("node", {}).get("text", "")[:100]
                    edges = media.get("edge_sidecar_to_children", {}).get("edges", [])
                    children = media.get("children") or []
                    if not edges and children:
                        edges = [{"node": c} for c in children]
                    if edges:
                        media_urls = []
                        for edge in edges:
                            child = edge.get("node", {})
                            child_video = child.get("video_url")
                            child_img = child.get("display_url") or child.get("thumbnail_src")
                            if child_video:
                                media_urls.append(("video", child_video))
                            elif child_img:
                                media_urls.append(("image", child_img))
                        if media_urls:
                            if img_index > 0:
                                target = max(0, min(img_index - 1, len(media_urls) - 1))
                                media_urls = [media_urls[target]]
                            files = _ig_download_media(media_urls, "ig_gql")
                    else:
                        video_url = media.get("video_url")
                        display_url = media.get("display_url")
                        if video_url:
                            f = download_file(video_url, "ig_gql_vid", "mp4", referer="https://www.instagram.com/")
                            if f:
                                files.append(f)
                        elif display_url:
                            f = download_file(display_url, "ig_gql_img", "jpg", referer="https://www.instagram.com/")
                            if f:
                                f = fix_extension(f)
                                files.append(f)
                    if files:
                        return files, title or "Instagram Media"
        except Exception as e:
            log.debug("ig graphql failed: %s", e)

        try:
            r = session.get(clean_url, headers={"User-Agent": UA}, timeout=15)
            html = r.text
            files = []
            title = ""
            for pattern in [
                r'window\.__additionalDataLoaded\s*\(\s*[^,]+,\s*({.+?})\s*\)',
                r'window\._sharedData\s*=\s*({.+?});\s*</script>',
            ]:
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        pdata = json.loads(match.group(1))
                        item = pdata.get("items", [{}])[0] if "items" in pdata else None
                        if not item:
                            post_page = pdata.get("entry_data", {}).get("PostPage", [{}])[0]
                            item = post_page.get("graphql", {}).get("shortcode_media", {})
                            if item:
                                edges = item.get("edge_sidecar_to_children", {}).get("edges", [])
                                if edges:
                                    media_urls = []
                                    for edge in edges:
                                        child = edge.get("node", {})
                                        cv = child.get("video_url")
                                        ci = child.get("display_url") or child.get("thumbnail_src")
                                        if cv:
                                            media_urls.append(("video", cv))
                                        elif ci:
                                            media_urls.append(("image", ci))
                                    if media_urls:
                                        if img_index > 0:
                                            target = max(0, min(img_index - 1, len(media_urls) - 1))
                                            media_urls = [media_urls[target]]
                                        files = _ig_download_media(media_urls, "ig_page")
                                else:
                                    video_url = item.get("video_url")
                                    display_url = item.get("display_url") or item.get("thumbnail_src")
                                    if video_url:
                                        f = download_file(video_url, "ig_page_vid", "mp4", referer="https://www.instagram.com/")
                                        if f:
                                            files.append(f)
                                    elif display_url:
                                        f = download_file(display_url, "ig_page_img", "jpg", referer="https://www.instagram.com/")
                                        if f:
                                            f = fix_extension(f)
                                            files.append(f)
                                caption_edges = item.get("edge_media_to_caption", {}).get("edges", [])
                                title = caption_edges[0].get("node", {}).get("text", "")[:100] if caption_edges else ""
                        else:
                            media_urls, title, _ = _ig_parse_item(item)
                            if media_urls:
                                if img_index > 0:
                                    target = max(0, min(img_index - 1, len(media_urls) - 1))
                                    media_urls = [media_urls[target]]
                                files = _ig_download_media(media_urls, "ig_page")
                        if files:
                            log.info("ig page scrape: found %d files", len(files))
                            return files, title or "Instagram Media"
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.debug("ig page scrape failed: %s", e)

        try:
            r = session.get(f"https://www.instagram.com/p/{sc}/embed/", headers={"User-Agent": UA}, timeout=15)
            html = r.text
            files = []
            title_m = re.search(r'<title>([^<]+)', html)
            title = title_m.group(1).strip()[:100] if title_m else ""
            for m in re.finditer(r'"video_url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"', html):
                vid_url = m.group(1).replace("\\u0026", "&")
                f = download_file(vid_url, f"ig_emb_{len(files)}", "mp4", referer="https://www.instagram.com/")
                if f:
                    files.append(f)
            if not files:
                for m in re.finditer(r'"display_url"\s*:\s*"(https?://[^"]+)"', html):
                    img_url = m.group(1).replace("\\u0026", "&")
                    f = download_file(img_url, f"ig_emb_{len(files)}", "jpg", referer="https://www.instagram.com/")
                    if f:
                        f = fix_extension(f)
                        files.append(f)
            if files:
                log.info("ig embed: found %d files", len(files))
                return files, title or "Instagram Media"
        except Exception as e:
            log.debug("ig embed failed: %s", e)

    except Exception as e:
        log.warning("ig download error: %s", e)
    log.info("ig download: all methods failed for %s", url[:80])
    return [], ""


def _playwright_instagram(url: str) -> Tuple[List[str], str]:
    if not PLAYWRIGHT_AVAILABLE:
        return [], ""
    files: List[str] = []
    title = "Instagram Media"
    try:
        with sync_playwright() as p:
            launch_args = {'headless': True, 'args': ['--disable-blink-features=Automation', '--no-sandbox']}
            browser = None
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
                context = browser.new_context(viewport={'width': 1280, 'height': 1200}, user_agent=UA)
                page = context.new_page()
                clean_url = url.split('?')[0]
                page.goto(clean_url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(4000)
                try:
                    title = page.title().split(' • ')[0][:100]
                except Exception:
                    pass
                media_urls = []
                for img in page.query_selector_all('img[src*="cdninstagram"]'):
                    src = img.get_attribute('src')
                    if src:
                        media_urls.append(src)
                for vid in page.query_selector_all('video[src*="cdninstagram"]'):
                    src = vid.get_attribute('src')
                    if src:
                        media_urls.append(src)
                seen = set()
                cookies = get_requests_cookies()
                for mu in list(dict.fromkeys(media_urls)):
                    mu_clean = mu.split('&_nc_cat')[0]
                    if mu_clean in seen:
                        continue
                    seen.add(mu_clean)
                    f = download_url(mu, "ig_pw", cookies=cookies, referer="https://www.instagram.com/")
                    if f:
                        files.append(f)
                    if len(files) >= 10:
                        break
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
        log.debug("playwright instagram failed: %s", e)
    return files, title
