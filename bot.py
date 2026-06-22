import asyncio
import os
import re
import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS
from database import db
from locales import t
from utils import track_user, check_subscription, home_kb, admin_kb, back_kb, build_channel_list_kb
from downloader import download_media
from media_modules import is_video_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")


def _compress_image(filepath: str, max_size: int = 800, quality: int = 75) -> Optional[str]:
    """Compress/validate image for Telegram upload. Returns path or None if invalid."""
    try:
        from PIL import Image
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".mp4", ".webm", ".mkv", ".avi", ".mov"):
            return filepath
        if not os.path.exists(filepath):
            return None

        img = Image.open(filepath)
        img.load()

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        w, h = img.size
        if w < 10 or h < 10:
            return None

        if w <= max_size and h <= max_size and ext == ".jpg":
            return filepath

        if w > max_size or h > max_size:
            ratio = min(max_size / w, max_size / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        new_path = filepath.rsplit(".", 1)[0] + "_c.jpg"
        img.save(new_path, "JPEG", quality=quality, optimize=True)

        if os.path.exists(new_path) and os.path.getsize(new_path) > 100:
            try:
                os.remove(filepath)
            except OSError:
                pass
            return new_path
        return filepath
    except Exception as e:
        log.debug("compress/validation failed for %s: %s", filepath, e)
        try:
            os.remove(filepath)
        except OSError:
            pass
        return None

app = Client("downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


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

    msg = await message.reply_text(t(uid, 'searching'))
    try:
        await msg.edit_text(t(uid, 'downloading'))
    except Exception:
        pass

    files, title = [], "Media"
    try:
        files, title = await asyncio.to_thread(download_media, url)
    except Exception as e:
        log.exception("download_media error: %s", e)

    if not files:
        try:
            await msg.edit_text(t(uid, 'error_link'))
        except Exception:
            pass
        return

    try:
        await msg.edit_text(t(uid, 'uploading'))
    except Exception:
        pass

    caption = f"✅ **{title}**"

    compressed = []
    for f in files:
        if not os.path.exists(f):
            log.warning("file missing before compress: %s", f)
            continue
        if is_video_file(f):
            compressed.append(f)
        else:
            c = _compress_image(f, max_size=800, quality=75)
            if c and os.path.exists(c):
                compressed.append(c)
            else:
                log.warning("compress returned invalid: %s -> %s", f, c)
    files = [f for f in compressed if os.path.exists(f)]
    log.info("uploading %d files: %s", len(files), [os.path.basename(f) for f in files])

    try:
        for i, fp in enumerate(files):
            try:
                if not os.path.exists(fp):
                    continue
                fsize = os.path.getsize(fp)
                if fsize < 100:
                    log.warning("skip tiny file %s (%d bytes)", fp, fsize)
                    continue
                cap = caption if i == 0 else None
                if is_video_file(fp):
                    await message.reply_video(fp, caption=cap, supports_streaming=True)
                else:
                    try:
                        await message.reply_photo(fp, caption=cap)
                    except Exception:
                        await message.reply_document(fp, caption=cap)
            except Exception as e:
                log.warning("upload file %d failed: %s", i, e)
            await asyncio.sleep(1)

        try:
            await msg.delete()
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

    threading.Thread(target=health_server, args=(8000,), daemon=True).start()
    threading.Thread(target=health_server, args=(8080,), daemon=True).start()
    print("Health server on port 8000 + 8080")

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
