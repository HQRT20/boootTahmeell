import asyncio
import os
import re
import json
import logging

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
import requests
import uuid
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS
from database import db
from locales import t
from utils import track_user, check_subscription, home_kb, admin_kb, back_kb, build_channel_list_kb
from downloader import download_media
from media_modules import is_video_file
from media_modules.youtube import download_youtube, download_youtube_audio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")


def _compress_image(filepath: str, max_size: int = 512, quality: int = 50) -> Optional[str]:
    """Compress image for Telegram. Returns path to valid JPEG or None."""
    try:
        from PIL import Image, ExifTags
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".mp4", ".webm", ".mkv", ".avi", ".mov"):
            return filepath
        if not os.path.exists(filepath):
            return None

        fsize = os.path.getsize(filepath)
        if fsize < 100:
            return None

        img = Image.open(filepath)
        img.load()

        try:
            exif = img._getexif()
            if exif:
                orient_key = next(k for k, v in ExifTags.TAGS.items() if v == "Orientation")
                orient = exif.get(orient_key)
                if orient == 3:
                    img = img.rotate(180, expand=True)
                elif orient == 6:
                    img = img.rotate(270, expand=True)
                elif orient == 8:
                    img = img.rotate(90, expand=True)
        except Exception:
            pass

        if img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        if w < 10 or h < 10:
            return None

        if w % 2 != 0:
            w -= 1
        if h % 2 != 0:
            h -= 1
        if (w, h) != img.size:
            img = img.resize((w, h), Image.LANCZOS)

        ratio = min(max_size / w, max_size / h) if (w > max_size or h > max_size) else 1.0
        new_w, new_h = int(w * ratio), int(h * ratio)
        if new_w % 2 != 0:
            new_w -= 1
        if new_h % 2 != 0:
            new_h -= 1

        if ratio < 1.0:
            img = img.resize((new_w, new_h), Image.LANCZOS)

        new_path = filepath.rsplit(".", 1)[0] + "_c.jpg"
        img.save(new_path, "JPEG", quality=quality, optimize=True, progressive=False, subsampling=0)

        if os.path.exists(new_path) and os.path.getsize(new_path) > 100:
            try:
                os.remove(filepath)
            except OSError:
                pass
            return new_path
        return filepath
    except Exception as e:
        log.warning("compress failed for %s: %s", filepath, e)
        return None

app = Client("downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


def _upload_to_telegraph(filepath: str) -> Optional[str]:
    """Upload file to telegra.ph and return the URL."""
    try:
        url = "https://telegra.ph/upload"
        with open(filepath, "rb") as f:
            resp = requests.post(url, files={"file": ("file.jpg", f, "image/jpeg")}, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data and "src" in data[0]:
                return "https://telegra.ph" + data[0]["src"]
        log.warning("telegraph response: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("telegraph upload failed: %s", e)
    return None


def _bot_api_send(chat_id: int, filepath: str, caption: str = "", is_video: bool = False, is_audio: bool = False) -> bool:
    """Send file directly via Telegram Bot API (bypasses Pyrogram DC2)."""
    clean_cap = (caption or "").replace("**", "").replace("__", "")
    fname = os.path.basename(filepath)
    ext = os.path.splitext(filepath)[1].lower()

    if is_audio:
        mime_map = {'.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.opus': 'audio/opus',
                     '.ogg': 'audio/ogg', '.wav': 'audio/wav', '.webm': 'audio/webm'}
        mime = mime_map.get(ext, 'audio/mpeg')
        methods = [("sendAudio", "audio", mime)]
    elif is_video:
        methods = [("sendVideo", "video", "video/mp4")]
    else:
        is_image = False
        try:
            from PIL import Image
            img = Image.open(filepath)
            img.verify()
            is_image = True
        except Exception:
            pass
        if is_image:
            methods = [("sendPhoto", "photo", "image/jpeg"), ("sendDocument", "document", "application/octet-stream")]
        else:
            methods = [("sendDocument", "document", "application/octet-stream")]

    for method, field, mime in methods:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
            data = {"chat_id": chat_id}
            if clean_cap:
                data["caption"] = clean_cap
            with open(filepath, "rb") as f:
                resp = requests.post(url, data=data, files={field: (fname, f, mime)}, timeout=120)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("ok"):
                    log.info("bot api %s sent OK to %s", method, chat_id)
                    return True
                log.warning("bot api %s ok=false: %s", method, str(result)[:200])
            else:
                log.warning("bot api %s HTTP %s: %s", method, resp.status_code, resp.text[:200])
        except Exception as e:
            log.warning("bot api %s failed: %s", method, e)
    return False


def _cleanup(files):
    for f in files or []:
        try:
            if f and os.path.exists(f):
                os.remove(f)
        except OSError as e:
            log.debug("cleanup failed for %s: %s", f, e)


# ── /start ──
@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    uid = message.from_user.id
    if uid in (db.get("banned_users") or []):
        return await message.reply_text(t(uid, 'banned'))

    track_user(uid)
    ok, btns = await check_subscription(client, uid)
    if not ok:
        return await message.reply_text(t(uid, 'subscribe_first'), reply_markup=InlineKeyboardMarkup(btns))

    await message.reply_text(t(uid, 'welcome'), reply_markup=home_kb(uid))
    if uid in ADMIN_IDS:
        await message.reply_text(t(uid, 'admin_title'), reply_markup=admin_kb(uid))


# ── Callbacks ──
@app.on_callback_query()
async def cb_handler(client, query):
    uid, data = query.from_user.id, query.data

    if data == "home":
        await query.message.edit_text(t(uid, 'welcome'), reply_markup=home_kb(uid))
    elif data == "help":
        await query.message.edit_text(t(uid, 'help_text'), reply_markup=back_kb(uid, "home"))
    elif data == "lang":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇸🇦 العربية", callback_data="set_ar"), InlineKeyboardButton("🇬🇧 English",  callback_data="set_en")],
            [InlineKeyboardButton(t(uid, 'back_btn'), callback_data="home")],
        ])
        await query.message.edit_text(t(uid, 'choose_lang'), reply_markup=kb)
    elif data.startswith("set_"):
        db.set(f"lang_{uid}", data[4:])
        await query.answer(t(uid, 'lang_changed'))
        await query.message.edit_text(t(uid, 'welcome'), reply_markup=home_kb(uid))

    # YouTube callbacks
    elif data.startswith("yt_audio:") or data.startswith("yt_video:"):
        parts = data.split(":", 2)
        if len(parts) < 3:
            return await query.answer("❌ رابط غير صالح")
        cb_uid = int(parts[1]) if parts[1].isdigit() else 0
        yt_url = parts[2]
        if uid != cb_uid:
            return await query.answer("❌ هذا الزر ليس لك!")

        is_audio = data.startswith("yt_audio:")
        label = "🎵 صوت (MP3)" if is_audio else "🎬 فيديو"
        try:
            await query.message.edit_text(f"⏳ جارٍ تحميل {label}...")
        except Exception:
            pass

        try:
            if is_audio:
                files, title = await asyncio.wait_for(
                    asyncio.to_thread(download_youtube_audio, yt_url),
                    timeout=120,
                )
            else:
                files, title = await asyncio.wait_for(
                    asyncio.to_thread(download_youtube, yt_url),
                    timeout=120,
                )
        except asyncio.TimeoutError:
            try:
                await query.message.edit_text("⏰ انتهت مهلة التحميل. حاول مرة أخرى.")
            except Exception:
                pass
            return
        except Exception as e:
            log.exception("yt download error: %s", e)
            try:
                await query.message.edit_text(f"❌ خطأ: {str(e)[:100]}")
            except Exception:
                pass
            return

        if not files:
            try:
                await query.message.edit_text("❌ فشل التحميل. تأكد من صحة الرابط.")
            except Exception:
                pass
            return

        try:
            await query.message.edit_text(f"📤 جارٍ رفع {label}...")
        except Exception:
            pass

        caption = f"✅ {title}"
        files = [f for f in files if os.path.exists(f) and os.path.getsize(f) > 100]

        for fp in files:
            is_vid = is_video_file(fp)
            ext = os.path.splitext(fp)[1].lower()
            is_aud = is_audio and ext in ('.mp3', '.m4a', '.opus', '.ogg', '.wav', '.webm')
            sent = await asyncio.to_thread(_bot_api_send, uid, fp, caption, is_vid, is_aud)
            if not sent:
                try:
                    if is_aud:
                        await asyncio.wait_for(query.message.reply_audio(fp, caption=caption), timeout=120)
                    elif is_vid:
                        await asyncio.wait_for(query.message.reply_video(fp, caption=caption, supports_streaming=True), timeout=120)
                    else:
                        await asyncio.wait_for(query.message.reply_document(fp, caption=caption), timeout=120)
                except Exception:
                    pass

        try:
            await query.message.edit_text("✅ تم بنجاح!")
        except Exception:
            pass
        await asyncio.sleep(2)
        try:
            await query.message.delete()
        except Exception:
            pass
        _cleanup(files)

    # Admin callbacks
    elif data.startswith("admin_") and uid in ADMIN_IDS:
        if data == "admin_home":
            db.delete(f"state_{uid}")
            await query.message.edit_text(t(uid, 'admin_title'), reply_markup=admin_kb(uid))
        elif data == "admin_stats":
            users, banned = db.get("user_ids") or [], db.get("banned_users") or []
            await query.message.edit_text(t(uid, 'stats_text', users=len(users), banned=len(banned)), reply_markup=back_kb(uid))
        elif data == "admin_broadcast":
            db.set(f"state_{uid}", "broadcast")
            await query.message.edit_text(t(uid, 'broadcast_prompt'), reply_markup=back_kb(uid))
        elif data == "admin_ban":
            db.set(f"state_{uid}", "ban")
            await query.message.edit_text(t(uid, 'ban_prompt'), reply_markup=back_kb(uid))
        elif data == "admin_unban":
            db.set(f"state_{uid}", "unban")
            await query.message.edit_text(t(uid, 'unban_prompt'), reply_markup=back_kb(uid))
        elif data == "admin_channels":
            db.delete(f"state_{uid}")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(t(uid, 'add_ch_btn'), callback_data="admin_add_ch")],
                [InlineKeyboardButton(t(uid, 'show_ch_btn'), callback_data="admin_show_ch")],
                [InlineKeyboardButton(t(uid, 'back_btn'), callback_data="admin_home")],
            ])
            await query.message.edit_text(t(uid, 'channels_btn'), reply_markup=kb)
        elif data == "admin_cookies":
            db.delete(f"state_{uid}")
            db.set(f"state_{uid}", "cookie_ig")
            await query.message.edit_text(
                "📤 ارسل محتوى ملف كوكيز Instagram:\n\n"
                "الصق محتوى الملف كاملاً هنا (تنسيق Netscape)",
                reply_markup=back_kb(uid, "admin_home")
            )
        elif data.startswith("admin_cookie_"):
            pass
        elif data == "admin_add_ch":
            db.set(f"state_{uid}", "add_ch")
            await query.message.edit_text(t(uid, 'add_ch_prompt'), reply_markup=back_kb(uid, "admin_channels"))
        elif data == "admin_show_ch":
            text, kb = await build_channel_list_kb(client, uid)
            await query.message.edit_text(text, reply_markup=kb)
        elif data.startswith("admin_del_"):
            ch_raw = data[10:]
            ch_id = None
            try:
                ch_id = int(ch_raw)
            except ValueError:
                ch_id = ch_raw
            channels = db.get("force_subscribe_channels") or []
            removed = False
            for i, ch in enumerate(channels):
                if ch == ch_id or str(ch) == str(ch_raw):
                    channels.pop(i)
                    removed = True
                    break
            if removed:
                db.set("force_subscribe_channels", channels)
            await query.answer(t(uid, 'ch_deleted'))
            text, kb = await build_channel_list_kb(client, uid)
            await query.message.edit_text(text, reply_markup=kb)


# ── Messages ──
@app.on_message(filters.private)
async def message_handler(client, message):
    uid, text = message.from_user.id, message.text or ""
    log.info(f"Received message from {uid}: {text}")
    if uid in (db.get("banned_users") or []):
        return

    # Admin State Machine
    state = db.get(f"state_{uid}")
    if state and uid in ADMIN_IDS:
        if state == "broadcast":
            db.delete(f"state_{uid}")
            users, count = db.get("user_ids") or [], 0
            for u in users:
                try:
                    await message.copy(u)
                    count += 1
                except Exception as e:
                    log.debug("broadcast to %s failed: %s", u, e)
                await asyncio.sleep(0.05)
            await message.reply_text(t(uid, 'broadcast_done', count=count))
        elif state in ("ban", "unban"):
            db.delete(f"state_{uid}")
            try:
                target = int(text.strip())
                banned = db.get("banned_users") or []
                if state == "ban":
                    if target not in banned:
                        banned.append(target)
                        db.set("banned_users", banned)
                    await message.reply_text(t(uid, 'ban_done'))
                else:
                    if target in banned:
                        banned.remove(target)
                        db.set("banned_users", banned)
                    await message.reply_text(t(uid, 'unban_done'))
            except ValueError:
                await message.reply_text(t(uid, 'invalid_id'))
        elif state == "add_ch":
            db.delete(f"state_{uid}")
            try:
                chat = await client.get_chat(text.strip())
                channels = db.get("force_subscribe_channels") or []
                if chat.id not in channels:
                    channels.append(chat.id)
                    db.set("force_subscribe_channels", channels)
                await message.reply_text(t(uid, 'ch_added', title=chat.title))
            except Exception as e:
                log.debug("add channel failed: %s", e)
                await message.reply_text(t(uid, 'ch_add_fail'))
        elif state.startswith("cookie_"):
            db.delete(f"state_{uid}")
            platform = state.replace("cookie_", "")
            files_map = {
                "ig": "instagram_cookies.txt",
            }
            cookie_file = files_map.get(platform)
            if cookie_file and text.strip():
                with open(cookie_file, "w", encoding="utf-8") as f:
                    f.write(text.strip())
                log.info("cookies updated for %s by admin %s", platform, uid)
                await message.reply_text(f"✅ تم حفظ كوكيز {platform.upper()} بنجاح في {cookie_file}")
            else:
                await message.reply_text("❌ بيانات غير صالحة")
        return

    # URL Handling
    match = re.search(r'(https?://[^\s<>"\'\]\)]+)', text)
    if not match:
        return

    url = match.group(1)
    track_user(uid)
    ok, btns = await check_subscription(client, uid)
    if not ok:
        return await message.reply_text(t(uid, 'subscribe_first'), reply_markup=InlineKeyboardMarkup(btns))

    url_lower = url.lower()
    is_youtube = any(d in url_lower for d in ("youtube.com", "youtu.be"))

    if is_youtube:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 تحميل صوت (MP3)", callback_data=f"yt_audio:{uid}:{url}")],
            [InlineKeyboardButton("🎬 تحميل فيديو", callback_data=f"yt_video:{uid}:{url}")],
        ])
        await message.reply_text(f"🔍 تم اكتشاف رابط يوتيوب\n\n🎬 اختر طريقة التحميل:", reply_markup=kb)
        return

    msg = await message.reply_text("🔍 جارٍ تحليل الرابط...")

    files, title = [], "Media"
    try:
        await msg.edit_text("⬇️ جارٍ تحميل الميديا...")
        files, title = await asyncio.wait_for(
            asyncio.to_thread(download_media, url),
            timeout=90,
        )
    except asyncio.TimeoutError:
        log.warning("download timed out after 90s for %s", url[:60])
        try:
            await msg.edit_text("⏰ انتهت مهلة التحميل (90 ثانية). حاول مرة أخرى.")
        except Exception:
            pass
        return
    except Exception as e:
        log.exception("download_media error: %s", e)
        try:
            await msg.edit_text(f"❌ خطأ أثناء التحميل: {str(e)[:100]}")
        except Exception:
            pass
        return

    if not files:
        try:
            await msg.edit_text(t(uid, 'error_link'))
        except Exception:
            pass
        return

    try:
        await msg.edit_text(f"✅ تم التحميل! ({len(files)} ملف) جارٍ الرفع...")
    except Exception:
        pass

    caption = f"✅ **{title}**"

    files = [f for f in files if os.path.exists(f) and os.path.getsize(f) > 100]
    log.info("uploading %d files: %s", len(files), [os.path.basename(f) for f in files])

    images = [f for f in files if not is_video_file(f)]
    videos = [f for f in files if is_video_file(f)]

    try:
        if len(images) > 1:
            try:
                await msg.edit_text(f"📤 جارٍ رفع الألبوم... ({len(images)} صورة)")
            except Exception:
                pass

            sent_album = False
            valid = [fp for fp in images if os.path.exists(fp) and os.path.getsize(fp) >= 100]
            if valid:
                try:
                    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
                    for batch_start in range(0, len(valid), 10):
                        batch = valid[batch_start:batch_start + 10]
                        media_json = []
                        files_dict = {}
                        for idx, fp in enumerate(batch):
                            tag = f"file{idx}"
                            if batch_start == 0 and idx == 0:
                                media_json.append({"type": "photo", "media": f"attach://{tag}", "caption": caption})
                            else:
                                media_json.append({"type": "photo", "media": f"attach://{tag}"})
                            files_dict[tag] = (os.path.basename(fp), open(fp, "rb"), "image/jpeg")
                        resp = requests.post(api_url, data={"chat_id": uid, "media": json.dumps(media_json)}, files=files_dict, timeout=120)
                        for _, _, fh in files_dict.values():
                            try:
                                fh.close()
                            except Exception:
                                pass
                        if resp.status_code == 200 and resp.json().get("ok"):
                            sent_album = True
                            log.info("album batch sent: %d images (offset %d)", len(batch), batch_start)
                        else:
                            log.warning("bot api album error: %s %s", resp.status_code, resp.text[:200])
                        await asyncio.sleep(1)
                except Exception as e:
                    log.warning("bot api album failed: %s", e)

            if not sent_album:
                try:
                    for batch_start in range(0, len(valid), 10):
                        batch = valid[batch_start:batch_start + 10]
                        await asyncio.wait_for(message.reply_media_group(
                            [InputMediaPhoto(fp, caption=caption if batch_start == 0 and i == 0 else "") for i, fp in enumerate(batch)]
                        ), timeout=120)
                        log.info("album batch sent via pyrogram: %d images", len(batch))
                        sent_album = True
                        await asyncio.sleep(1)
                except Exception as e:
                    log.warning("pyrogram album failed: %s", e)

            if not sent_album:
                try:
                    await msg.edit_text("📤 جارٍ رفع الصور واحد واحد...")
                except Exception:
                    pass
                for i, fp in enumerate(images):
                    if not os.path.exists(fp) or os.path.getsize(fp) < 100:
                        continue
                    try:
                        await msg.edit_text(f"📤 جارٍ رفع الصورة {i+1}/{len(images)}...")
                    except Exception:
                        pass
                    cap = caption if i == 0 else ""
                    sent = await asyncio.to_thread(_bot_api_send, uid, fp, cap, False)
                    if not sent:
                        try:
                            await asyncio.wait_for(message.reply_document(fp, caption=cap), timeout=60)
                        except Exception:
                            pass
                    await asyncio.sleep(1)

        elif len(images) == 1:
            try:
                await msg.edit_text("📤 جارٍ رفع الصورة...")
            except Exception:
                pass
            fp = images[0]
            if os.path.exists(fp) and os.path.getsize(fp) >= 100:
                log.info("processing single image %s", os.path.basename(fp))
                sent = await asyncio.to_thread(_bot_api_send, uid, fp, caption, False)
                if not sent:
                    try:
                        await asyncio.wait_for(message.reply_document(fp, caption=caption), timeout=60)
                    except Exception:
                        pass
                log.info("delivered: %s", os.path.basename(fp))

        for i, fp in enumerate(videos):
            try:
                if not os.path.exists(fp) or os.path.getsize(fp) < 100:
                    continue
                try:
                    await msg.edit_text(f"📤 جارٍ رفع الفيديو {i+1}/{len(videos)}...")
                except Exception:
                    pass
                cap = caption if i == 0 and not images else ""
                log.info("processing video %s (%d bytes)", os.path.basename(fp), os.path.getsize(fp))
                sent = await asyncio.to_thread(_bot_api_send, uid, fp, cap, True)
                if not sent:
                    try:
                        await asyncio.wait_for(message.reply_video(fp, caption=cap, supports_streaming=True), timeout=60)
                    except Exception:
                        pass
                log.info("delivered: %s", os.path.basename(fp))
                await asyncio.sleep(1)
            except Exception as e:
                log.warning("video upload failed: %s", e)

        try:
            await msg.edit_text("✅ تم بنجاح!")
        except Exception:
            pass
        await asyncio.sleep(2)
        try:
            await msg.delete()
        except Exception:
            pass
        except Exception:
            pass
    except Exception as e:
        log.exception("upload error: %s", e)
        try:
            await msg.edit_text(t(uid, 'error_general'))
        except Exception:
            pass
    finally:
        _cleanup(files)


if __name__ == "__main__":
    import threading
    import socket
    import time

    def health_server(port):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", port))
            srv.listen(5)
            while True:
                try:
                    conn, _ = srv.accept()
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                    conn.close()
                except Exception:
                    pass
        except OSError:
            pass

    render_port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=health_server, args=(render_port,), daemon=True).start()
    threading.Thread(target=health_server, args=(8000,), daemon=True).start()
    print(f"Health server on port {render_port} + 8000")

    while True:
        try:
            print("Bot starting...")
            app.run()
        except Exception as e:
            if "FLOOD_WAIT" in str(e):
                import re as _re
                wait_match = _re.search(r'A wait of (\d+) seconds', str(e))
                wait_sec = int(wait_match.group(1)) if wait_match else 1200
                print(f"FloodWait: waiting {wait_sec} seconds before retry...")
                time.sleep(wait_sec)
            else:
                print(f"Bot crashed: {e}")
                time.sleep(30)
