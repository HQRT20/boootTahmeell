import os
import shutil
import logging
from typing import List, Tuple

import yt_dlp
from config import DOWNLOADS_DIR
from media_modules._utils import build_ydl_opts, find_file

log = logging.getLogger("downloader.youtube")

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def download_youtube(url: str) -> Tuple[List[str], str]:
    files, title = _download_with_ytdlp(url, for_images=False)
    return files, title or "YouTube Media"


def download_youtube_audio(url: str) -> Tuple[List[str], str]:
    files: List[str] = []
    title = "YouTube Audio"
    try:
        opts = build_ydl_opts()
        opts['format'] = 'bestaudio/best'
        opts['outtmpl'] = f'{DOWNLOADS_DIR}/%(id)s.%(ext)s'

        if HAS_FFMPEG:
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }]
            log.info("yt-dlp audio (ffmpeg mp3): %s", url[:60])
        else:
            log.info("yt-dlp audio (no ffmpeg, raw): %s", url[:60])

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = (info.get('title') or info.get('description') or title)[:100]
                vid_id = info.get('id', '')
                if HAS_FFMPEG:
                    mp3_path = os.path.join(DOWNLOADS_DIR, f"{vid_id}.mp3")
                    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 100:
                        files.append(mp3_path)
                if not files:
                    for ext in ('mp3', 'm4a', 'opus', 'ogg', 'wav', 'webm'):
                        p = os.path.join(DOWNLOADS_DIR, f"{vid_id}.{ext}")
                        if os.path.exists(p) and os.path.getsize(p) > 100:
                            files.append(p)
                            break
                if not files:
                    for f in os.listdir(DOWNLOADS_DIR):
                        if f.startswith(vid_id) and os.path.getsize(os.path.join(DOWNLOADS_DIR, f)) > 100:
                            files.append(os.path.join(DOWNLOADS_DIR, f))
                            break
        log.info("yt-dlp audio done: %d files", len(files))
    except Exception as e:
        log.exception("yt-dlp audio failed: %s", e)
    return files, title


def _download_with_ytdlp(url: str, for_images: bool = False) -> Tuple[List[str], str]:
    files: List[str] = []
    seen: set = set()
    title = "Media"
    try:
        opts = build_ydl_opts(for_images=for_images)
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
