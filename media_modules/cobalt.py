import os
import re
import uuid
import json
import logging
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
            r = requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=120)
            if r.status_code != 200:
                if attempt < retries:
                    import time; time.sleep(1)
                    continue
                return None
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
            size = os.path.getsize(filepath)
            if size < 256:
                try:
                    os.remove(filepath)
                except OSError:
                    pass
                return None
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


def download_instagram_api(url: str) -> Tuple[List[str], str]:
    """Download Instagram by scraping the page for video/image URLs."""
    try:
        clean_url = url.split("?")[0].rstrip("/")

        # Try mobile API first (less restrictive)
        shortcode = re.search(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)', clean_url)
        if shortcode:
            sc = shortcode.group(1)
            mobile_api = f"https://www.instagram.com/p/{sc}/embed/"
            try:
                r_embed = requests.get(
                    mobile_api,
                    headers={"User-Agent": UA, "Accept": "text/html"},
                    timeout=15,
                )
                if r_embed.status_code == 200:
                    files = []
                    title = ""
                    title_m = re.search(r'<title>([^<]+)', r_embed.text)
                    if title_m:
                        title = title_m.group(1).strip()[:100]
                    for m in re.finditer(r'"video_url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"', r_embed.text):
                        vid_url = m.group(1).replace("\\u0026", "&")
                        f = _dl(vid_url, f"ig_emb_{len(files)}", "mp4")
                        if f:
                            files.append(f)
                        if len(files) >= 10:
                            break
                    if not files:
                        for m in re.finditer(r'"display_url"\s*:\s*"(https?://[^"]+)"', r_embed.text):
                            img_url = m.group(1).replace("\\u0026", "&")
                            f = _dl(img_url, f"ig_emb_{len(files)}", "jpg")
                            if f:
                                f = _fix_extension(f)
                                files.append(f)
                            if len(files) >= 10:
                                break
                    if not files:
                        for m in re.finditer(r'src="(https?://[^"]*cdninstagram[^"]*)"', r_embed.text):
                            media_url = m.group(1)
                            ext = "mp4" if "video" in media_url else "jpg"
                            f = _dl(media_url, f"ig_emb_{len(files)}", ext)
                            if f:
                                f = _fix_extension(f)
                                files.append(f)
                            if len(files) >= 10:
                                break
                    if files:
                        return files, title or "Instagram Media"
            except Exception as e:
                log.debug("instagram embed scrape failed: %s", e)

        # Fallback: direct page scrape
        r = requests.get(
            clean_url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "X-IG-App-ID": "936619743392459",
                "Sec-Fetch-Mode": "navigate",
            },
            timeout=15,
        )
        if r.status_code != 200:
            return [], ""

        title = ""
        title_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:title"', r.text)
        if not title_m:
            title_m = re.search(r'<title>([^<]+)', r.text)
        if title_m:
            title = title_m.group(1).strip()[:100]

        files = []

        video_m = re.search(
            r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:video"',
            r.text,
        )
        if video_m:
            vid_url = video_m.group(1)
            f = _dl(vid_url, "ig_vid", "mp4")
            if f:
                files.append(f)

        if not files:
            for match in re.finditer(
                r'"video_url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
                r.text,
            ):
                vid_url = match.group(1).replace("\\u0026", "&")
                f = _dl(vid_url, f"ig_vid_{len(files)}", "mp4")
                if f:
                    files.append(f)
                if len(files) >= 10:
                    break

        if not files:
            for match in re.finditer(
                r'"display_url"\s*:\s*"(https?://[^"]+)"',
                r.text,
            ):
                img_url = match.group(1).replace("\\u0026", "&")
                f = _dl(img_url, f"ig_img_{len(files)}", "jpg")
                if f:
                    f = _fix_extension(f)
                    files.append(f)
                if len(files) >= 10:
                    break

        if not files:
            img_m = re.search(
                r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:image"',
                r.text,
            )
            if img_m:
                f = _dl(img_m.group(1), "ig_img", "jpg")
                if f:
                    f = _fix_extension(f)
                    files.append(f)

        if files:
            return files, title or "Instagram Media"

    except Exception as e:
        log.debug("instagram scrape failed: %s", e)
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

        # Try to get og:video first (for video pins)
        video_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:video"', r.text)
        if video_m:
            f = _dl(video_m.group(1), "pin_vid", "mp4")
            if f:
                return [f], title or "Pinterest Video"

        # Get og:image (the main pin image)
        img_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:image"', r.text)
        if img_m:
            img_url = img_m.group(1)
            # Get highest resolution
            img_url = re.sub(r'/\d+x\d+/', '/originals/', img_url)
            f = _dl(img_url, "pin_img", "jpg")
            if f:
                return [f], title or "Pinterest Image"

        # Fallback: get largest pinimg image
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
