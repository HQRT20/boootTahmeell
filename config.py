import os
from dotenv import load_dotenv

load_dotenv()

try:
    API_ID = int(os.getenv("API_ID", "0"))
except (ValueError, TypeError):
    API_ID = 0

API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

try:
    ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
except (ValueError, TypeError):
    ADMIN_IDS = []

DOWNLOADS_DIR = "downloads"
COOKIES_FILE  = "cookies.txt"

COBALT_INSTANCES = [
    x.strip() for x in os.getenv(
        "COBALT_INSTANCES",
        "cobalt-backend.canine.tools,cobalt-api.meowing.de,capi.3kh0.net"
    ).split(",") if x.strip()
]

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
