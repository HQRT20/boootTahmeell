import os
import re
import uuid
import time
import http.cookiejar
import logging
from typing import List, Tuple, Optional

import requests
from config import DOWNLOADS_DIR, COOKIES_FILE

log = logging.getLogger("downloader.utils")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

MEDIA_EXTS = ("mp4", "mkv", "webm", "mov", "avi", "m4v", "jpg", "jpeg", "png", "webp", "gif")
VIDEO_EXTS = ("mp4", "mkv", "webm", "mov", "avi", "m4v")
AUDIO_EXTS = ("mp3", "m4a", "opus", "ogg", "wav", "webm")


# ── File Download ──────────────────────────────────────────────

def download_file(url: str, prefix: str, ext: str = "mp4",
                  referer: Optional[str] = None, retries: int = 2) -> Optional[str]:
    for attempt in range(retries + 1):
        try:
            filepath = os.path.join(DOWNLOADS_DIR, f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}")
            headers = {"User-Agent": UA, "Accept": "*/*"}
            if referer:
                headers["Referer"] = referer
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                if attempt < retries:
                    time.sleep(1)
                    continue
                return None
            ct = r.headers.get("content-type", "")
            data = r.content
            if len(data) < 256:
                if attempt < retries:
                    time.sleep(1)
                    continue
                return None
            if "text/html" in ct:
                return None
            with open(filepath, "wb") as f:
                f.write(data)
            return filepath
        except Exception as e:
            log.debug("download_file attempt %d failed: %s", attempt + 1, e)
            if attempt < retries:
                time.sleep(1)
    return None


def download_url(url: str, prefix: str = "file", cookies=None,
                 referer: Optional[str] = None) -> Optional[str]:
    try:
        ext = _guess_ext_from_url(url)
        filepath = os.path.join(DOWNLOADS_DIR, f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}")
        headers = {"User-Agent": UA}
        if referer:
            headers["Referer"] = referer
        with requests.get(url, headers=headers, cookies=cookies, stream=True, timeout=30) as r:
            if r.status_code != 200:
                return None
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(filepath) < 256:
            try:
                os.remove(filepath)
            except OSError:
                pass
            return None
        return filepath
    except Exception as e:
        log.debug("download_url error: %s", e)
        return None


# ── File Detection ─────────────────────────────────────────────

def is_video_file(path: str) -> bool:
    return path.lower().rsplit(".", 1)[-1] in VIDEO_EXTS


def is_audio_file(path: str) -> bool:
    return path.lower().rsplit(".", 1)[-1] in AUDIO_EXTS


def fix_extension(filepath: str) -> str:
    try:
        with open(filepath, "rb") as f:
            header = f.read(16)
    except Exception:
        return filepath
    real_ext = None
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        real_ext = "png"
    elif header[:3] == b"\xff\xd8\xff":
        real_ext = "jpg"
    elif header[:4] == b"GIF8":
        real_ext = "gif"
    elif header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        real_ext = "webp"
    elif header[:4] in (b"\x00\x00\x00\x1c", b"\x00\x00\x00\x18", b"\x00\x00\x00 "):
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


def find_file(base_path: str) -> Optional[str]:
    if os.path.exists(base_path):
        return base_path
    stem = base_path.rsplit(".", 1)[0]
    for ext in MEDIA_EXTS:
        p = f"{stem}.{ext}"
        if os.path.exists(p):
            return p
    return None


# ── yt-dlp Options ─────────────────────────────────────────────

def build_ydl_opts(for_images: bool = False, platform: str = "") -> dict:
    opts = {
        "outtmpl": f"{DOWNLOADS_DIR}/%(id)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "ignore_no_formats_error": True,
        "http_chunk_size": 1048576,
        "retries": 2,
        "fragment_retries": 2,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "http_timeout": 30,
    }
    if for_images:
        opts["format"] = "best[ext=jpg]/best[ext=jpeg]/best[ext=png]/best[ext=webp]/best"
    else:
        opts["format"] = "best[acodec!=none][ext=mp4]/best[acodec!=none]/best"
    cookie_file = _find_cookie_file(platform)
    if cookie_file:
        opts["cookiefile"] = cookie_file
    return opts


def _find_cookie_file(platform: str = "") -> Optional[str]:
    candidates = [COOKIES_FILE, "instagram_cookies.txt"]
    for f in candidates:
        if f and os.path.exists(f):
            return f
    return None


# ── Cookies Helpers ────────────────────────────────────────────

def get_requests_cookies() -> Optional[http.cookiejar.CookieJar]:
    if not os.path.exists(COOKIES_FILE):
        return None
    try:
        cj = http.cookiejar.MozillaCookieJar(COOKIES_FILE)
        cj.load(ignore_discard=True, ignore_expires=True)
        return cj
    except Exception:
        return None


def get_playwright_cookies() -> List[dict]:
    if not os.path.exists(COOKIES_FILE):
        return []
    out: List[dict] = []
    try:
        cj = http.cookiejar.MozillaCookieJar(COOKIES_FILE)
        cj.load(ignore_discard=True, ignore_expires=True)
        for c in cj:
            cookie: dict = {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "httpOnly": bool(c.has_nonstandard_attr("HttpOnly")),
                "secure": bool(c.secure),
                "sameSite": "Lax",
            }
            if c.expires and c.expires > 0:
                cookie["expires"] = c.expires
            out.append(cookie)
    except Exception:
        pass
    return out


# ── Internal Helpers ───────────────────────────────────────────

def _guess_ext_from_url(url: str) -> str:
    url_lower = url.split("?", 1)[0].lower()
    for ext in ("mp4", "webm", "mkv", "gif", "jpg", "jpeg", "png", "webp"):
        if url_lower.endswith("." + ext):
            return ext
    m = re.search(r"format=(jpg|jpeg|png|webp|mp4)", url, re.I)
    if m:
        return m.group(1).lower()
    return "bin"
