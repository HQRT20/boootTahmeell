---
title: Telegram Media Downloader
emoji: ⬇️
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 8080
pinned: false
---

# Telegram Media Downloader Bot

Download media from TikTok, Instagram, YouTube, and Pinterest.

## Features

- TikTok videos (no watermark)
- Instagram posts, reels, stories, carousels
- YouTube videos and MP3 audio
- Pinterest images and videos

## Environment Variables

Set these in HF Spaces Settings → Variables and Secrets:

| Variable | Description |
|----------|-------------|
| `API_ID` | Telegram API ID |
| `API_HASH` | Telegram API Hash |
| `BOT_TOKEN` | Bot token from @BotFather |
| `ADMIN_IDS` | Comma-separated admin user IDs |
| `IG_COOKIES` | Instagram cookies (optional) |
