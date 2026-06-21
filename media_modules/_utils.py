import os, re, uuid, http.cookiejar, logging
from typing import List, Tuple, Optional

import requests
from config import DOWNLOADS_DIR, COOKIES_FILE

log = logging.getLogger("downloader.utils")

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')

MEDIA_EXTS = ('mp4', 'mkv', 'webm', 'mov', 'avi', 'm4v', 'jpg', 'jpeg', 'png', 'webp', 'gif')
VIDEO_EXTS = ('mp4', 'mkv', 'webm', 'mov', 'avi', 'm4v')

def build_ydl_opts(for_images: bool = False) -> dict:
    base = {
        'outtmpl': f'{DOWNLOADS_DIR}/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'ignore_no_formats_error': True,
        'http_chunk_size': 1048576,
        'retries': 3,
        'fragment_retries': 3,
        'noplaylist': False,
        'extract_flat': False,
    }
    if for_images:
        base['format'] = 'best[ext=jpg]/best[ext=jpeg]/best[ext=png]/best[ext=webp]/best'
    else:
        base['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    if os.path.exists(COOKIES_FILE):
        base['cookiefile'] = COOKIES_FILE
    return base

def get_requests_cookies() -> Optional[http.cookiejar.CookieJar]:
    if not os.path.exists(COOKIES_FILE):
        return None
    try:
        cj = http.cookiejar.MozillaCookieJar(COOKIES_FILE)
        cj.load(ignore_discard=True, ignore_expires=True)
        return cj
    except Exception as e:
        log.debug("cookie load failed: %s", e)
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
    except Exception as e:
        log.debug("playwright cookie load failed: %s", e)
    return out

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

def guess_ext_from_url(url: str) -> str:
    url_lower = url.split('?', 1)[0].lower()
    for ext in ('mp4', 'webm', 'mkv', 'gif', 'jpg', 'jpeg', 'png', 'webp'):
        if url_lower.endswith('.' + ext):
            return ext
    m = re.search(r'format=(jpg|jpeg|png|webp|mp4)', url, re.I)
    if m:
        return m.group(1).lower()
    return 'bin'

def download_url(url: str, prefix: str = "file", cookies=None, referer: Optional[str] = None) -> Optional[str]:
    try:
        ext = guess_ext_from_url(url)
        if ext == 'bin':
            ext = 'jpg' if 'pbs.twimg.com' in url else 'mp4' if 'video.twimg.com' in url else 'bin'
        filepath = os.path.join(DOWNLOADS_DIR, f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}")
        headers = {'User-Agent': UA}
        if referer:
            headers['Referer'] = referer
        with requests.get(url, headers=headers, cookies=cookies, stream=True, timeout=30) as r:
            if r.status_code != 200:
                log.debug("download %s -> HTTP %s", url[:80], r.status_code)
                return None
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(filepath) < 256:
            try: os.remove(filepath)
            except OSError: pass
            return None
        return filepath
    except Exception as e:
        log.debug("download error for %s: %s", url[:80], e)
        return None

def find_brave_exe() -> Optional[str]:
    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    root = r"C:\Program Files\BraveSoftware\Brave-Browser\Application"
    if os.path.isdir(root):
        for name in os.listdir(root):
            cand = os.path.join(root, name, "brave.exe")
            if os.path.exists(cand):
                return cand
    return None

def download_with_ytdlp(url: str, for_images: bool = False) -> Tuple[List[str], str]:
    import yt_dlp
    files: List[str] = []
    seen: set = set()
    title = "Media"
    try:
        with yt_dlp.YoutubeDL(build_ydl_opts(for_images=for_images)) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = (info.get('title') or info.get('description') or title)[:100]
                entries = info.get('entries') or [info]
                for entry in entries:
                    if not entry: continue
                    f = find_file(ydl.prepare_filename(entry))
                    if f and f not in seen:
                        seen.add(f)
                        files.append(f)
    except Exception as e:
        log.exception("yt-dlp failed: %s", e)
    return files, title
