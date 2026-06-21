import time
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import ADMIN_IDS
from database import db
from locales import t
from typing import Tuple, List, Union

def track_user(uid: int):
    """Tracks unique user IDs in the database."""
    users = db.get("user_ids") or []
    if uid not in users:
        users.append(uid)
        db.set("user_ids", users)

async def check_subscription(client: Client, uid: int) -> Tuple[bool, List[List[InlineKeyboardButton]]]:
    """Checks if a user is subscribed to forced channels."""
    channels = db.get("force_subscribe_channels") or []
    not_joined = []
    for ch in channels:
        try:
            member = await client.get_chat_member(ch, uid)
            if member.status in ("left", "kicked"):
                not_joined.append(ch)
        except Exception:
            not_joined.append(ch)
            
    if not not_joined:
        return True, []
        
    btns = []
    for ch in not_joined:
        try:
            chat = await client.get_chat(ch)
            link = chat.invite_link or f"https://t.me/{chat.username}"
            btns.append([InlineKeyboardButton(f"Join {chat.title}", url=link)])
        except Exception:
            btns.append([InlineKeyboardButton(f"Join Channel ({ch})", url=f"https://t.me/{ch}")])
    return False, btns

def home_kb(uid: int) -> InlineKeyboardMarkup:
    """Returns the main home keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, 'help_btn'), callback_data="help"),
         InlineKeyboardButton(t(uid, 'lang_btn'), callback_data="lang")]
    ])

def admin_kb(uid: int) -> InlineKeyboardMarkup:
    """Returns the main admin keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, 'stats_btn'), callback_data="admin_stats"),
         InlineKeyboardButton(t(uid, 'broadcast_btn'), callback_data="admin_broadcast")],
        [InlineKeyboardButton(t(uid, 'ban_btn'), callback_data="admin_ban"),
         InlineKeyboardButton(t(uid, 'unban_btn'), callback_data="admin_unban")],
        [InlineKeyboardButton(t(uid, 'channels_btn'), callback_data="admin_channels")],
    ])

def back_kb(uid: int, target: str = "admin_home") -> InlineKeyboardMarkup:
    """Standard back button keyboard."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(uid, 'back_btn'), callback_data=target)]])

async def build_channel_list_kb(client: Client, uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Builds the channel list with delete buttons for admins."""
    channels = db.get("force_subscribe_channels") or []
    if not channels:
        return t(uid, 'no_channels'), back_kb(uid, "admin_channels")
        
    rows = []
    text = "📢 **Forced Subscription Channels:**\n\n"
    for ch in channels:
        try:
            chat = await client.get_chat(ch)
            title = chat.title
            text += f"• {title} (`{ch}`)\n"
            rows.append([InlineKeyboardButton(f"🗑 Delete {title}", callback_data=f"admin_del_{ch}")])
        except Exception:
            text += f"• `{ch}`\n"
            rows.append([InlineKeyboardButton(f"🗑 Delete {ch}", callback_data=f"admin_del_{ch}")])
            
    rows.append([InlineKeyboardButton(t(uid, 'back_btn'), callback_data="admin_channels")])
    return text, InlineKeyboardMarkup(rows)
