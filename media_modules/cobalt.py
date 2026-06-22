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

        is_reel = "/reel/" in url.lower()

        img_index = 0
        idx_match = re.search(r'img_index=(\d+)', url)
        if idx_match:
            img_index = int(idx_match.group(1))

        shortcode = re.search(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)', clean_url)
        if shortcode:
            sc = shortcode.group(1)

            ig_api_url = f"https://www.instagram.com/api/v1/media/shortcode/{sc}/info/"
            try:
                r_api = requests.get(
                    ig_api_url,
                    headers={"User-Agent": UA, "X-IG-App-ID": "936619743392459"},
                    timeout=10,
                )
                if r_api.status_code == 200:
                    adata = r_api.json()
                    media = adata.get("items") or []
                    if media:
                        item = media[0]
                        title = (item.get("caption", {}) or {}).get("text", "")[:100] if isinstance(item.get("caption"), dict) else ""
                        is_vid = item.get("media_type") == 2
                        if is_vid:
                            vs = item.get("video_versions") or []
                            if vs:
                                best = max(vs, key=lambda v: v.get("width", 0) * v.get("height", 0))
                                f = _dl(best["url"], "ig_api_vid", "mp4")
                                if f:
                                    return [f], title or "Instagram Video"
                        else:
                            carousel = item.get("carousel_media") or []
                            files = []
                            if img_index > 0 and carousel:
                                target_idx = max(0, min(img_index - 1, len(carousel) - 1))
                                ci = carousel[target_idx]
                                ci_type = ci.get("media_type")
                                if ci_type == 2:
                                    vs = ci.get("video_versions") or []
                                    if vs:
                                        best = max(vs, key=lambda v: v.get("width", 0) * v.get("height", 0))
                                        f = _dl(best["url"], "ig_api_vid", "mp4")
                                        if f:
                                            files.append(f)
                                else:
                                    imgs = ci.get("image_versions2", {}).get("candidates") or []
                                    if imgs:
                                        best = max(imgs, key=lambda i: i.get("width", 0) * i.get("height", 0))
                                        f = _dl(best["url"], "ig_api_img", "jpg")
                                        if f:
                                            f = _fix_extension(f)
                                            files.append(f)
                            elif carousel:
                                for ci in carousel:
                                    ci_type = ci.get("media_type")
                                    if ci_type == 2:
                                        vs = ci.get("video_versions") or []
                                        if vs:
                                            best = max(vs, key=lambda v: v.get("width", 0) * v.get("height", 0))
                                            f = _dl(best["url"], f"ig_api_vid_{len(files)}", "mp4")
                                            if f:
                                                files.append(f)
                                    else:
                                        imgs = ci.get("image_versions2", {}).get("candidates") or []
                                        if imgs:
                                            best = max(imgs, key=lambda i: i.get("width", 0) * i.get("height", 0))
                                            f = _dl(best["url"], f"ig_api_img_{len(files)}", "jpg")
                                            if f:
                                                f = _fix_extension(f)
                                                files.append(f)
                                    if len(files) >= 10:
                                        break
                            else:
                                imgs = item.get("image_versions2", {}).get("candidates") or []
                                if imgs:
                                    best = max(imgs, key=lambda i: i.get("width", 0) * i.get("height", 0))
                                    f = _dl(best["url"], "ig_api_img", "jpg")
                                    if f:
                                        f = _fix_extension(f)
                                        files.append(f)
                            if files:
                                return files, title or "Instagram Media"
            except Exception as e:
                log.debug("ig api info failed for %s: %s", sc, e)

            oembed_url = f"https://www.instagram.com/api/v1/oembed/?url=https://www.instagram.com/p/{sc}/"
            try:
                r_oembed = requests.get(oembed_url, headers={"User-Agent": UA}, timeout=10)
                if r_oembed.status_code == 200:
                    odata = r_oembed.json()
                    thumbnail = odata.get("thumbnail_url") or ""
                    if thumbnail:
                        f = _dl(thumbnail, "ig_oe", "jpg")
                        if f:
                            f = _fix_extension(f)
                            if f:
                                title = (odata.get("title") or "")[:100]
                                return [f], title or "Instagram Media"
            except Exception as e:
                log.debug("oembed failed for %s: %s", sc, e)

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
                        for m in re.finditer(r'src="(https?://[^"]*cdninstagram[^"]*/v/[^"]*)"', r_embed.text):
                            media_url = m.group(1).replace("\\u0026", "&")
                            f = _dl(media_url, f"ig_emb_{len(files)}", "mp4")
                            if f:
                                f = _fix_extension(f)
                                files.append(f)
                            if len(files) >= 1:
                                break

                    if not files and not is_reel:
                        all_imgs = []
                        for m in re.finditer(r'"display_url"\s*:\s*"(https?://[^"]+)"', r_embed.text):
                            img_url = m.group(1).replace("\\u0026", "&")
                            if img_url not in all_imgs:
                                all_imgs.append(img_url)

                        if not all_imgs:
                            for m in re.finditer(r'"image_versions2".*?"url"\s*:\s*"(https?://[^"]+)"', r_embed.text):
                                img_url = m.group(1).replace("\\u0026", "&")
                                if img_url not in all_imgs:
                                    all_imgs.append(img_url)

                        if not all_imgs:
                            for m in re.finditer(r'src="(https?://[^"]*cdninstagram[^"]*)"', r_embed.text):
                                img_url = m.group(1).replace("\\u0026", "&")
                                if img_url not in all_imgs and "/v/" not in img_url:
                                    all_imgs.append(img_url)

                        if not all_imgs:
                            og_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]*\s+property="og:image"', r_embed.text)
                            if og_m:
                                all_imgs.append(og_m.group(1).replace("\\u0026", "&"))

                        if all_imgs:
                            if img_index > 0:
                                target_idx = max(0, min(img_index - 1, len(all_imgs) - 1))
                                f = _dl(all_imgs[target_idx], "ig_emb", "jpg")
                                if f:
                                    f = _fix_extension(f)
                                    files.append(f)
                            else:
                                for img_url in all_imgs[:10]:
                                    f = _dl(img_url, f"ig_emb_{len(files)}", "jpg")
                                    if f:
                                        f = _fix_extension(f)
                                        files.append(f)

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
            for match in re.finditer(
                r'"image_versions2".*?"url"\s*:\s*"(https?://[^"]+)"',
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
            for match in re.finditer(
                r'src="(https?://[^"]*cdninstagram[^"]*\.jpg[^"]*)"',
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
