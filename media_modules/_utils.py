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

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

MEDIA_EXTS = ('mp4', 'mkv', 'webm', 'mov', 'avi', 'm4v', 'jpg', 'jpeg', 'png', 'webp', 'gif')
VIDEO_EXTS = ('mp4', 'mkv', 'webm', 'mov', 'avi', 'm4v')


def download_file(url: str, prefix: str, ext: str = "mp4",
                  referer: Optional[str] = None, retries: int = 2) -> Optional[str]:
    """Download a file from URL with retries. Returns filepath or None."""
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
            log.debug("download_file attempt %d failed for %s: %s", attempt + 1, url[:80], e)
            if attempt < retries:
                time.sleep(1)
    return None


def fix_extension(filepath: str) -> str:
    """Detect real file type by magic bytes and rename if needed."""
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


def detect_ext(url: str, content_type: str = "") -> str:
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


def build_ydl_opts(for_images: bool = False, platform: str = "") -> dict:
    base = {
        'outtmpl': f'{DOWNLOADS_DIR}/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'ignore_no_formats_error': True,
        'http_chunk_size': 1048576,
        'retries': 2,
        'fragment_retries': 2,
        'noplaylist': True,
        'extract_flat': False,
        'socket_timeout': 30,
        'http_timeout': 30,
    }
    if for_images:
        base['format'] = 'best[ext=jpg]/best[ext=jpeg]/best[ext=png]/best[ext=webp]/best'
    else:
        base['format'] = 'best[acodec!=none][ext=mp4]/best[acodec!=none]/best'
    cookie_file = _find_cookie_file(platform)
    if cookie_file:
        base['cookiefile'] = cookie_file
    return base


def _find_cookie_file(platform: str = "") -> Optional[str]:
    candidates = []
    if platform == "instagram":
        from config import COOKIES_FILE
        candidates.append(COOKIES_FILE)
        candidates.append("instagram_cookies.txt")
    else:
        from config import COOKIES_FILE
        candidates.append(COOKIES_FILE)
        candidates.append("instagram_cookies.txt")
    for f in candidates:
        if f and os.path.exists(f):
            return f
    return None


def is_video_file(path: str) -> bool:
    return path.lower().rsplit('.', 1)[-1] in VIDEO_EXTS


def find_file(base_path: str) -> Optional[str]:
    if os.path.exists(base_path):
        return base_path
    stem = base_path.rsplit('.', 1)[0]
    for ext in MEDIA_EXTS:
        p = f"{stem}.{ext}"
        if os.path.exists(p):
            return p
    return None


def download_url(url: str, prefix: str = "file", cookies=None, referer: Optional[str] = None) -> Optional[str]:
    try:
        ext = _guess_ext_from_url(url)
        if ext == 'bin':
            ext = 'jpg' if 'pbs.twimg.com' in url else 'mp4' if 'video.twimg.com' in url else 'bin'
        filepath = os.path.join(DOWNLOADS_DIR, f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}")
        headers = {'User-Agent': UA}
        if referer:
            headers['Referer'] = referer
        with requests.get(url, headers=headers, cookies=cookies, stream=True, timeout=30) as r:
            if r.status_code != 200:
                return None
            with open(filepath, 'wb') as f:
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
        log.debug("download_url error for %s: %s", url[:80], e)
        return None


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
                'name': c.name,
                'value': c.value,
                'domain': c.domain,
                'path': c.path,
                'httpOnly': bool(c.has_nonstandard_attr('HttpOnly')),
                'secure': bool(c.secure),
                'sameSite': 'Lax',
            }
            if c.expires and c.expires > 0:
                cookie['expires'] = c.expires
            out.append(cookie)
    except Exception:
        pass
    return out


def download_with_ytdlp(url: str, for_images: bool = False, platform: str = "") -> Tuple[List[str], str]:
    import yt_dlp
    files: List[str] = []
    seen: set = set()
    title = "Media"
    try:
        opts = build_ydl_opts(for_images=for_images, platform=platform)
        log.info("yt-dlp starting: images=%s url=%s", for_images, url[:60])
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = (info.get('title') or info.get('description') or title)[:100]
                entries = info.get('entries') or [info]
                for entry in entries:
                    if not entry:
                        continue
                    f = find_file(ydl.prepare_filename(entry))
                    if f and f not in seen:
                        seen.add(f)
                        files.append(f)
        log.info("yt-dlp done: %d files", len(files))
    except Exception as e:
        log.exception("yt-dlp failed: %s", e)
    return files, title


def find_brave_exe() -> Optional[str]:
    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _guess_ext_from_url(url: str) -> str:
    url_lower = url.split('?', 1)[0].lower()
    for ext in ('mp4', 'webm', 'mkv', 'gif', 'jpg', 'jpeg', 'png', 'webp'):
        if url_lower.endswith('.' + ext):
            return ext
    m = re.search(r'format=(jpg|jpeg|png|webp|mp4)', url, re.I)
    if m:
        return m.group(1).lower()
    return 'bin'
