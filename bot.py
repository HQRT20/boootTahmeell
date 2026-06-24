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
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS
from database import db
from locales import t
from utils import track_user, check_subscription, home_kb, admin_kb, back_kb, build_channel_list_kb
from downloader import download_media
from media_modules._utils import is_video_file, is_audio_file
from media_modules.youtube import download_youtube, download_youtube_audio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

app = Client("downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


# ══════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════

def _bot_api_send(chat_id: int, filepath: str, caption: str = "",
                  is_video: bool = False, is_audio: bool = False) -> bool:
    clean_cap = (caption or "").replace("**", "").replace("__", "")
    fname = os.path.basename(filepath)
    ext = os.path.splitext(filepath)[1].lower()

    if is_audio:
        mime_map = {
            ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".opus": "audio/opus",
            ".ogg": "audio/ogg", ".wav": "audio/wav", ".webm": "audio/webm",
        }
        mime = mime_map.get(ext, "audio/mpeg")
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
            methods = [
                ("sendPhoto", "photo", "image/jpeg"),
                ("sendDocument", "document", "application/octet-stream"),
            ]
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
            if resp.status_code == 200 and resp.json().get("ok"):
                log.info("bot api %s sent OK to %s", method, chat_id)
                return True
            log.warning("bot api %s failed: %s %s", method, resp.status_code, resp.text[:200])
        except Exception as e:
            log.warning("bot api %s error: %s", method, e)
    return False


def _cleanup(files):
    for f in files or []:
        try:
            if f and os.path.exists(f):
                os.remove(f)
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    uid = message.from_user.id
    if uid in (db.get("banned_users") or []):
        return await message.reply_text(t(uid, "banned"))

    track_user(uid)
    ok, btns = await check_subscription(client, uid)
    if not ok:
        return await message.reply_text(t(uid, "subscribe_first"), reply_markup=InlineKeyboardMarkup(btns))

    await message.reply_text(t(uid, "welcome"), reply_markup=home_kb(uid))
    if uid in ADMIN_IDS:
        await message.reply_text(t(uid, "admin_title"), reply_markup=admin_kb(uid))


# ══════════════════════════════════════════════════════════════
#  Callbacks
# ══════════════════════════════════════════════════════════════

@app.on_callback_query()
async def cb_handler(client, query):
    uid, data = query.from_user.id, query.data

    # ── Navigation ──
    if data == "home":
        return await query.message.edit_text(t(uid, "welcome"), reply_markup=home_kb(uid))
    elif data == "help":
        return await query.message.edit_text(t(uid, "help_text"), reply_markup=back_kb(uid, "home"))
    elif data == "lang":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇸🇦 العربية", callback_data="set_ar"),
             InlineKeyboardButton("🇬🇧 English", callback_data="set_en")],
            [InlineKeyboardButton(t(uid, "back_btn"), callback_data="home")],
        ])
        return await query.message.edit_text(t(uid, "choose_lang"), reply_markup=kb)
    elif data.startswith("set_"):
        db.set(f"lang_{uid}", data[4:])
        await query.answer(t(uid, "lang_changed"))
        return await query.message.edit_text(t(uid, "welcome"), reply_markup=home_kb(uid))

    # ── YouTube Download ──
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
            dl_fn = download_youtube_audio if is_audio else download_youtube
            files, title = await asyncio.wait_for(asyncio.to_thread(dl_fn, yt_url), timeout=120)
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
            vid = is_video_file(fp)
            aud = is_audio and is_audio_file(fp)
            sent = await asyncio.to_thread(_bot_api_send, uid, fp, caption, vid, aud)
            if not sent:
                try:
                    if aud:
                        await asyncio.wait_for(query.message.reply_audio(fp, caption=caption), timeout=120)
                    elif vid:
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

    # ── Admin Panel ──
    elif data.startswith("admin_") and uid in ADMIN_IDS:
        await _handle_admin(client, query, uid, data)


async def _handle_admin(client, query, uid, data):
    if data == "admin_home":
        db.delete(f"state_{uid}")
        await query.message.edit_text(t(uid, "admin_title"), reply_markup=admin_kb(uid))

    elif data == "admin_stats":
        users, banned = db.get("user_ids") or [], db.get("banned_users") or []
        await query.message.edit_text(t(uid, "stats_text", users=len(users), banned=len(banned)), reply_markup=back_kb(uid))

    elif data == "admin_broadcast":
        db.set(f"state_{uid}", "broadcast")
        await query.message.edit_text(t(uid, "broadcast_prompt"), reply_markup=back_kb(uid))

    elif data == "admin_ban":
        db.set(f"state_{uid}", "ban")
        await query.message.edit_text(t(uid, "ban_prompt"), reply_markup=back_kb(uid))

    elif data == "admin_unban":
        db.set(f"state_{uid}", "unban")
        await query.message.edit_text(t(uid, "unban_prompt"), reply_markup=back_kb(uid))

    elif data == "admin_channels":
        db.delete(f"state_{uid}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(uid, "add_ch_btn"), callback_data="admin_add_ch")],
            [InlineKeyboardButton(t(uid, "show_ch_btn"), callback_data="admin_show_ch")],
            [InlineKeyboardButton(t(uid, "back_btn"), callback_data="admin_home")],
        ])
        await query.message.edit_text(t(uid, "channels_btn"), reply_markup=kb)

    elif data == "admin_cookies":
        db.delete(f"state_{uid}")
        db.set(f"state_{uid}", "cookie_ig")
        await query.message.edit_text(
            "📤 ارسل محتوى ملف كوكيز Instagram:\n\nالصق محتوى الملف كاملاً هنا (تنسيق Netscape)",
            reply_markup=back_kb(uid, "admin_home"),
        )

    elif data == "admin_add_ch":
        db.set(f"state_{uid}", "add_ch")
        await query.message.edit_text(t(uid, "add_ch_prompt"), reply_markup=back_kb(uid, "admin_channels"))

    elif data == "admin_show_ch":
        text, kb = await build_channel_list_kb(client, uid)
        await query.message.edit_text(text, reply_markup=kb)

    elif data.startswith("admin_del_"):
        ch_raw = data[10:]
        ch_id = int(ch_raw) if ch_raw.isdigit() else ch_raw
        channels = db.get("force_subscribe_channels") or []
        for i, ch in enumerate(channels):
            if ch == ch_id or str(ch) == str(ch_raw):
                channels.pop(i)
                db.set("force_subscribe_channels", channels)
                break
        await query.answer(t(uid, "ch_deleted"))
        text, kb = await build_channel_list_kb(client, uid)
        await query.message.edit_text(text, reply_markup=kb)


# ══════════════════════════════════════════════════════════════
#  Messages
# ══════════════════════════════════════════════════════════════

@app.on_message(filters.private)
async def message_handler(client, message):
    uid, text = message.from_user.id, message.text or ""
    log.info("msg from %d: %s", uid, text[:80])

    if uid in (db.get("banned_users") or []):
        return

    # ── Admin State Machine ──
    state = db.get(f"state_{uid}")
    if state and uid in ADMIN_IDS:
        await _handle_admin_message(client, message, uid, text, state)
        return

    # ── URL Handling ──
    match = re.search(r"(https?://[^\s<>\"'\]\)]+)", text)
    if not match:
        return

    url = match.group(1)
    track_user(uid)
    ok, btns = await check_subscription(client, uid)
    if not ok:
        return await message.reply_text(t(uid, "subscribe_first"), reply_markup=InlineKeyboardMarkup(btns))

    url_lower = url.lower()
    is_youtube = any(d in url_lower for d in ("youtube.com", "youtu.be"))

    # YouTube → show choice buttons
    if is_youtube:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 تحميل صوت (MP3)", callback_data=f"yt_audio:{uid}:{url}")],
            [InlineKeyboardButton("🎬 تحميل فيديو", callback_data=f"yt_video:{uid}:{url}")],
        ])
        return await message.reply_text("🔍 تم اكتشاف رابط يوتيوب\n\n🎬 اختر طريقة التحميل:", reply_markup=kb)

    # Other platforms → download directly
    msg = await message.reply_text("🔍 جارٍ تحليل الرابط...")
    files, title = [], "Media"
    try:
        await msg.edit_text("⬇️ جارٍ تحميل الميديا...")
        files, title = await asyncio.wait_for(asyncio.to_thread(download_media, url), timeout=90)
    except asyncio.TimeoutError:
        try:
            await msg.edit_text("⏰ انتهت مهلة التحميل (90 ثانية). حاول مرة أخرى.")
        except Exception:
            pass
        return
    except Exception as e:
        log.exception("download error: %s", e)
        try:
            await msg.edit_text(f"❌ خطأ أثناء التحميل: {str(e)[:100]}")
        except Exception:
            pass
        return

    if not files:
        try:
            await msg.edit_text(t(uid, "error_link"))
        except Exception:
            pass
        return

    await _upload_files(message, msg, uid, files, title)


async def _handle_admin_message(client, message, uid, text, state):
    db.delete(f"state_{uid}")

    if state == "broadcast":
        users, count = db.get("user_ids") or [], 0
        for u in users:
            try:
                await message.copy(u)
                count += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await message.reply_text(t(uid, "broadcast_done", count=count))

    elif state in ("ban", "unban"):
        try:
            target = int(text.strip())
            banned = db.get("banned_users") or []
            if state == "ban":
                if target not in banned:
                    banned.append(target)
                    db.set("banned_users", banned)
                await message.reply_text(t(uid, "ban_done"))
            else:
                if target in banned:
                    banned.remove(target)
                    db.set("banned_users", banned)
                await message.reply_text(t(uid, "unban_done"))
        except ValueError:
            await message.reply_text(t(uid, "invalid_id"))

    elif state == "add_ch":
        try:
            chat = await client.get_chat(text.strip())
            channels = db.get("force_subscribe_channels") or []
            if chat.id not in channels:
                channels.append(chat.id)
                db.set("force_subscribe_channels", channels)
            await message.reply_text(t(uid, "ch_added", title=chat.title))
        except Exception:
            await message.reply_text(t(uid, "ch_add_fail"))

    elif state == "cookie_ig":
        if text.strip():
            with open("instagram_cookies.txt", "w", encoding="utf-8") as f:
                f.write(text.strip())
            log.info("ig cookies updated by admin %s", uid)
            await message.reply_text("✅ تم حفظ كوكيز Instagram بنجاح")
        else:
            await message.reply_text("❌ بيانات غير صالحة")


# ══════════════════════════════════════════════════════════════
#  Upload Logic
# ══════════════════════════════════════════════════════════════

async def _upload_files(message, msg, uid, files, title):
    try:
        await msg.edit_text(f"✅ تم التحميل! ({len(files)} ملف) جارٍ الرفع...")
    except Exception:
        pass

    caption = f"✅ **{title}**"
    files = [f for f in files if os.path.exists(f) and os.path.getsize(f) > 100]
    log.info("uploading %d files", len(files))

    images = [f for f in files if not is_video_file(f)]
    videos = [f for f in files if is_video_file(f)]

    try:
        # Multiple images → album
        if len(images) > 1:
            await _upload_album(message, msg, uid, images, caption)

        # Single image
        elif len(images) == 1:
            try:
                await msg.edit_text("📤 جارٍ رفع الصورة...")
            except Exception:
                pass
            fp = images[0]
            if os.path.exists(fp) and os.path.getsize(fp) >= 100:
                sent = await asyncio.to_thread(_bot_api_send, uid, fp, caption)
                if not sent:
                    try:
                        await asyncio.wait_for(message.reply_document(fp, caption=caption), timeout=60)
                    except Exception:
                        pass

        # Videos
        for i, fp in enumerate(videos):
            if not os.path.exists(fp) or os.path.getsize(fp) < 100:
                continue
            try:
                await msg.edit_text(f"📤 جارٍ رفع الفيديو {i + 1}/{len(videos)}...")
            except Exception:
                pass
            cap = caption if i == 0 and not images else ""
            sent = await asyncio.to_thread(_bot_api_send, uid, fp, cap, True)
            if not sent:
                try:
                    await asyncio.wait_for(message.reply_video(fp, caption=cap, supports_streaming=True), timeout=60)
                except Exception:
                    pass
            await asyncio.sleep(1)

        try:
            await msg.edit_text("✅ تم بنجاح!")
        except Exception:
            pass
        await asyncio.sleep(2)
        try:
            await msg.delete()
        except Exception:
            pass

    except Exception as e:
        log.exception("upload error: %s", e)
        try:
            await msg.edit_text(t(uid, "error_general"))
        except Exception:
            pass
    finally:
        _cleanup(files)


async def _upload_album(message, msg, uid, images, caption):
    try:
        await msg.edit_text(f"📤 جارٍ رفع الألبوم... ({len(images)} صورة)")
    except Exception:
        pass

    sent_album = False
    valid = [fp for fp in images if os.path.exists(fp) and os.path.getsize(fp) >= 100]

    # Try Bot API first
    if valid:
        try:
            api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
            for batch_start in range(0, len(valid), 10):
                batch = valid[batch_start:batch_start + 10]
                media_json = []
                files_dict = {}
                for idx, fp in enumerate(batch):
                    tag = f"file{idx}"
                    cap = caption if batch_start == 0 and idx == 0 else ""
                    media_json.append({"type": "photo", "media": f"attach://{tag}", "caption": cap})
                    files_dict[tag] = (os.path.basename(fp), open(fp, "rb"), "image/jpeg")
                resp = requests.post(api_url, data={"chat_id": uid, "media": json.dumps(media_json)}, files=files_dict, timeout=120)
                for _, _, fh in files_dict.values():
                    try:
                        fh.close()
                    except Exception:
                        pass
                if resp.status_code == 200 and resp.json().get("ok"):
                    sent_album = True
                await asyncio.sleep(1)
        except Exception as e:
            log.warning("bot api album failed: %s", e)

    # Fallback to Pyrogram
    if not sent_album:
        try:
            for batch_start in range(0, len(valid), 10):
                batch = valid[batch_start:batch_start + 10]
                await asyncio.wait_for(message.reply_media_group(
                    [InputMediaPhoto(fp, caption=caption if batch_start == 0 and i == 0 else "") for i, fp in enumerate(batch)]
                ), timeout=120)
                sent_album = True
                await asyncio.sleep(1)
        except Exception as e:
            log.warning("pyrogram album failed: %s", e)

    # Last resort: one by one
    if not sent_album:
        try:
            await msg.edit_text("📤 جارٍ رفع الصور واحد واحد...")
        except Exception:
            pass
        for i, fp in enumerate(images):
            if not os.path.exists(fp) or os.path.getsize(fp) < 100:
                continue
            try:
                await msg.edit_text(f"📤 جارٍ رفع الصورة {i + 1}/{len(images)}...")
            except Exception:
                pass
            cap = caption if i == 0 else ""
            sent = await asyncio.to_thread(_bot_api_send, uid, fp, cap)
            if not sent:
                try:
                    await asyncio.wait_for(message.reply_document(fp, caption=cap), timeout=60)
                except Exception:
                    pass
            await asyncio.sleep(1)


# ══════════════════════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════════════════════

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
                wait_match = _re.search(r"A wait of (\d+) seconds", str(e))
                wait_sec = int(wait_match.group(1)) if wait_match else 1200
                print(f"FloodWait: waiting {wait_sec}s...")
                time.sleep(wait_sec)
            else:
                print(f"Bot crashed: {e}")
                time.sleep(30)
