import os
import re
import uuid
import json
import logging
import urllib.parse
import requests
from typing import List, Tuple, Optional

from config import DOWNLOADS_DIR

log = logging.getLogger("downloader.cobalt")


def _fix_extension(filepath: str) -> str:
    """Detect real file type and rename if needed."""
    try:
        with open(filepath, "rb") as f:
            header = f.read(16)
    except Exception:
        return filepath

    real_ext = None
    if header[:8] == b'\x89PNG\r\n\x1a\n':
        real_ext = "png"
    elif header[:3] == b'\xff\xd8\xff':
        real_ext = "jpg"
    elif header[:4] == b'GIF8':
        real_ext = "gif"
    elif header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        real_ext = "webp"
    elif header[:4] in (b'\x00\x00\x00\x1c', b'\x00\x00\x00\x18', b'\x00\x00\x00 '):
        real_ext = "mp4"

    if real_ext:
        cur_ext = os.path.splitext(filepath)[1].lstrip(".")
        if cur_ext != real_ext:
            new_path = os.path.splitext(filepath)[0] + "." + real_ext
            try:
                os.rename(filepath, new_path)
                return new_path
            except OSError:
                pass
    return filepath

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def _dl(url: str, prefix: str, ext: str = "mp4", retries: int = 2) -> Optional[str]:
    for attempt in range(retries + 1):
        try:
            filepath = os.path.join(DOWNLOADS_DIR, f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}")
            headers = {
                "User-Agent": UA,
                "Accept": "*/*",
                "Referer": "https://www.instagram.com/",
            }
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                if attempt < retries:
                    import time; time.sleep(1)
                    continue
                return None
            ct = r.headers.get("content-type", "")
            data = r.content
            if len(data) < 256:
                if attempt < retries:
                    import time; time.sleep(1)
                    continue
                return None
            if "text/html" in ct:
                log.debug("_dl got HTML from %s (ct=%s)", url[:80], ct)
                return None
            with open(filepath, "wb") as f:
                f.write(data)
            return filepath
        except Exception as e:
            log.debug("_dl attempt %d failed for %s: %s", attempt + 1, url[:80], e)
            if attempt < retries:
                import time; time.sleep(1)
    return None


def _detect_ext(url: str, content_type: str = "") -> str:
    url_lower = url.split("?")[0].lower()
    for ext in ("mp4", "webm", "mkv", "mov", "jpg", "jpeg", "png", "webp", "gif", "mp3", "ogg"):
        if url_lower.endswith(f".{ext}"):
            return ext
    if "video" in content_type:
        return "mp4"
    if "image" in content_type:
        return "jpg"
    if "audio" in content_type:
        return "mp3"
    return "mp4"


def download_tikwm(url: str) -> Tuple[List[str], str]:
    """Download TikTok via tikwm.com API (no watermark, HD)."""
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
        files = []

        if info.get("hdplay"):
            f = _dl(info["hdplay"], "tt_hd")
            if f:
                files.append(f)

        if not files and info.get("play"):
            f = _dl(info["play"], "tt_play")
            if f:
                files.append(f)

        if not files and info.get("wmplay"):
            f = _dl(info["wmplay"], "tt_wm")
            if f:
                files.append(f)

        if files:
            return files, title or "TikTok Video"

        images = info.get("images") or []
        for i, img_url in enumerate(images[:10]):
            if isinstance(img_url, str):
                f = _dl(img_url, f"tt_img_{i}", "jpg")
                if f:
                    files.append(f)
        if files:
            return files, title or "TikTok Slideshow"

    except Exception as e:
        log.debug("tikwm failed: %s", e)
    return [], ""


def download_twitter_api(url: str) -> Tuple[List[str], str]:
    """Download Twitter/X media via fxtwitter API."""
    m = re.search(r'(?:x|twitter)\.com/([^/?#]+)/status(?:es)?/(\d+)', url)
    if not m:
        m = re.search(r'(?:x|twitter)\.com/i/(?:web/)?status/(\d+)', url)
        if m:
            handle, tid = None, m.group(1)
        else:
            return [], ""
    else:
        handle, tid = m.group(1), m.group(2)

    apis = []
    if handle:
        apis.append(f"https://api.fxtwitter.com/{handle}/status/{tid}")
    apis.append(f"https://api.fxtwitter.com/status/{tid}")

    for api in apis:
        try:
            r = requests.get(api, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            tweet = data.get("tweet") or data
            if not isinstance(tweet, dict):
                continue

            title = ""
            text = tweet.get("text") or tweet.get("full_text") or ""
            if text:
                title = text.strip().split("\n")[0][:100]

            files = []
            media = tweet.get("media") or {}
            if isinstance(media, dict):
                for vid in media.get("videos") or []:
                    variants = vid.get("variants") or []
                    best = None
                    for v in variants:
                        if v.get("content_type", "").endswith("mp4"):
                            if not best or (v.get("bitrate") or 0) > (best.get("bitrate") or 0):
                                best = v
                    if not best and variants:
                        best = variants[0]
                    if best and best.get("url"):
                        f = _dl(best["url"], "tw_vid")
                        if f:
                            files.append(f)

                for photo in media.get("photos") or []:
                    photo_url = photo.get("url")
                    if photo_url:
                        f = _dl(photo_url + "?name=orig", "tw_pic", "jpg")
                        if f:
                            files.append(f)

            if files:
                return files, title or "Twitter Media"

        except Exception as e:
            log.debug("fxtwitter failed for %s: %s", api, e)
    return [], ""


def _shortcode_to_mediaid(shortcode):
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    media_id = 0
    for char in shortcode:
        media_id = media_id * 64 + alphabet.index(char)
    return str(media_id)


def _get_ig_session(url):
    """Visit Instagram page to get cookies for API requests."""
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
    try:
        s.get(url, timeout=15)
    except Exception:
        pass
    return s


def _ig_parse_item(item):
    """Parse an Instagram API item into (file_urls, title, is_video)."""
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
            if len(files) >= 10:
                break
    else:
        imgs = (item.get("image_versions2") or {}).get("candidates") or []
        if imgs:
            best = max(imgs, key=lambda i: i.get("width", 0) * i.get("height", 0))
            if best.get("url"):
                files.append(("image", best["url"]))

    return files, title, is_video


def download_instagram_api(url: str) -> Tuple[List[str], str]:
    """Download Instagram using 4-layer extraction (API → GraphQL → Page → Embed)."""
    try:
        clean_url = url.split("?")[0].rstrip("/")
        shortcode_match = re.search(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)', clean_url)
        if not shortcode_match:
            return [], ""
        sc = shortcode_match.group(1)
        log.info("ig download: shortcode=%s url=%s", sc, url[:80])

        session = _get_ig_session(clean_url)
        media_id = _shortcode_to_mediaid(sc)

        # Method 1: API
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
                    media_urls, title, is_video = _ig_parse_item(items[0])
                    if media_urls:
                        log.info("ig api: found %d media items", len(media_urls))
                        files = []
                        for kind, murl in media_urls:
                            prefix = "ig_vid" if kind == "video" else "ig_img"
                            ext = "mp4" if kind == "video" else "jpg"
                            f = _dl(murl, prefix, ext)
                            if f:
                                if kind == "image":
                                    f = _fix_extension(f)
                                files.append(f)
                        if files:
                            return files, title or "Instagram Media"
        except Exception as e:
            log.debug("ig api failed: %s", e)

        # Method 2: GraphQL
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
                    log.info("ig graphql: found media")
                    files = []
                    video_url = media.get("video_url")
                    display_url = media.get("display_url")
                    if video_url:
                        f = _dl(video_url, "ig_gql_vid", "mp4")
                        if f:
                            files.append(f)
                    elif display_url:
                        f = _dl(display_url, "ig_gql_img", "jpg")
                        if f:
                            f = _fix_extension(f)
                            files.append(f)
                    if files:
                        caption_edges = media.get("edge_media_to_caption", {}).get("edges", [])
                        title = caption_edges[0].get("node", {}).get("text", "")[:100] if caption_edges else ""
                        return files, title or "Instagram Media"
        except Exception as e:
            log.debug("ig graphql failed: %s", e)

        # Method 3: Page HTML scrape (window.__additionalDataLoaded / _sharedData)
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
                                video_url = item.get("video_url")
                                display_url = item.get("display_url") or item.get("thumbnail_src")
                                if video_url:
                                    f = _dl(video_url, "ig_page_vid", "mp4")
                                    if f:
                                        files.append(f)
                                elif display_url:
                                    f = _dl(display_url, "ig_page_img", "jpg")
                                    if f:
                                        f = _fix_extension(f)
                                        files.append(f)
                                caption_edges = item.get("edge_media_to_caption", {}).get("edges", [])
                                title = caption_edges[0].get("node", {}).get("text", "")[:100] if caption_edges else ""
                        else:
                            media_urls, title, is_video = _ig_parse_item(item)
                            for kind, murl in media_urls:
                                prefix = "ig_page_vid" if kind == "video" else "ig_page_img"
                                ext = "mp4" if kind == "video" else "jpg"
                                f = _dl(murl, prefix, ext)
                                if f:
                                    if kind == "image":
                                        f = _fix_extension(f)
                                    files.append(f)
                        if files:
                            log.info("ig page scrape: found %d files", len(files))
                            return files, title or "Instagram Media"
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.debug("ig page scrape failed: %s", e)

        # Method 4: Embed (last resort, extract from data tags)
        try:
            r = session.get(f"https://www.instagram.com/p/{sc}/embed/", headers={"User-Agent": UA}, timeout=15)
            html = r.text
            files = []
            title_m = re.search(r'<title>([^<]+)', html)
            title = title_m.group(1).strip()[:100] if title_m else ""

            for m in re.finditer(r'"video_url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"', html):
                vid_url = m.group(1).replace("\\u0026", "&")
                f = _dl(vid_url, f"ig_emb_{len(files)}", "mp4")
                if f:
                    files.append(f)
                if len(files) >= 10:
                    break

            if not files:
                for m in re.finditer(r'"display_url"\s*:\s*"(https?://[^"]+)"', html):
                    img_url = m.group(1).replace("\\u0026", "&")
                    f = _dl(img_url, f"ig_emb_{len(files)}", "jpg")
                    if f:
                        f = _fix_extension(f)
                        files.append(f)
                    if len(files) >= 10:
                        break

            if files:
                log.info("ig embed: found %d files", len(files))
                return files, title or "Instagram Media"
        except Exception as e:
            log.debug("ig embed failed: %s", e)

    except Exception as e:
        log.warning("ig download error: %s", e)

    log.info("ig download: all methods failed for %s", url[:80])
    return [], ""


def download_pinterest_api(url: str) -> Tuple[List[str], str]:
    """Download Pinterest via direct page scraping - only the main pin."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, allow_redirects=True, timeout=20)
        if r.status_code != 200:
            return [], ""

        title = ""
        m = re.search(r'<title>([^<]+)', r.text)
        if m:
            title = m.group(1).split("|")[0].strip()[:100]

        video_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:video"', r.text)
        if video_m:
            f = _dl(video_m.group(1), "pin_vid", "mp4")
            if f:
                return [f], title or "Pinterest Video"

        img_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:image"', r.text)
        if img_m:
            img_url = img_m.group(1)
            img_url = re.sub(r'/\d+x\d+/', '/originals/', img_url)
            f = _dl(img_url, "pin_img", "jpg")
            if f:
                f = _fix_extension(f)
                return [f], title or "Pinterest Image"

        urls = []
        for match in re.finditer(
            r'https://i\.pinimg\.com/originals/[^\s"\'<>]+',
            r.text,
        ):
            u = match.group(0).split('"')[0].split("'")[0].split('<')[0]
            if u not in urls:
                urls.append(u)

        if not urls:
            for match in re.finditer(
                r'https://i\.pinimg\.com/\d+x\d+/[^\s"\'<>]+',
                r.text,
            ):
                u = match.group(0).split('"')[0].split("'")[0].split('<')[0]
                if u not in urls and "75x75" not in u:
                    urls.append(u)

        files = []
        for u in urls[:1]:
            ext = _detect_ext(u)
            f = _dl(u, "pin_img", ext)
            if f:
                f = _fix_extension(f)
                files.append(f)

        if files:
            return files, title or "Pinterest Media"

    except Exception as e:
        log.debug("pinterest scrape failed: %s", e)
    return [], ""


def download_facebook_api(url: str) -> Tuple[List[str], str]:
    """Download Facebook via fbdown API."""
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
            f = _dl(u, "fb_vid")
            if f:
                files.append(f)

        if files:
            return files, title or "Facebook Video"

    except Exception as e:
        log.debug("fbdown failed: %s", e)
    return [], ""
