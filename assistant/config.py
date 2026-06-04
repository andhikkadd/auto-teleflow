import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Pre-initialize logging config
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("Config")

def parse_bool(value) -> bool:
    if not value:
        return False
    return str(value).lower() in ("true", "1", "yes", "on")

# Bot settings
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required in assistant/.env")

ADMIN_TELEGRAM_ID_RAW = os.getenv("ADMIN_TELEGRAM_ID", "").strip()
if not ADMIN_TELEGRAM_ID_RAW:
    raise ValueError("ADMIN_TELEGRAM_ID is required in assistant/.env")
try:
    ADMIN_TELEGRAM_ID = int(ADMIN_TELEGRAM_ID_RAW)
except ValueError:
    raise ValueError("ADMIN_TELEGRAM_ID must be a valid integer")

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/bot.db").strip()

# Web Panel Settings
ENABLE_WEB_PANEL = parse_bool(os.getenv("ENABLE_WEB_PANEL", "true"))
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1").strip()
try:
    WEB_PORT = int(os.getenv("WEB_PORT", "8001"))
except ValueError:
    WEB_PORT = 8001

WEB_ADMIN_USERNAME = os.getenv("WEB_ADMIN_USERNAME", "admin").strip()
WEB_ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "").strip()
WEB_SESSION_SECRET = os.getenv("WEB_SESSION_SECRET", "").strip()

if ENABLE_WEB_PANEL:
    if not WEB_ADMIN_PASSWORD:
        raise ValueError("WEB_ADMIN_PASSWORD is required in assistant/.env when Web Panel is enabled")
    if WEB_ADMIN_PASSWORD.lower() in ("admin", "password", "123456", "12345678", "root", "qwerty"):
        raise ValueError("WEB_ADMIN_PASSWORD is too weak/default. Please set a strong, custom password")
    if WEB_ADMIN_USERNAME.lower() in ("admin", "root") and WEB_ADMIN_PASSWORD.lower() == WEB_ADMIN_USERNAME.lower():
        raise ValueError("WEB_ADMIN_PASSWORD cannot be the same as WEB_ADMIN_USERNAME")
    if not WEB_SESSION_SECRET:
        raise ValueError("WEB_SESSION_SECRET is required in assistant/.env when Web Panel is enabled")
    if WEB_SESSION_SECRET.lower() in ("secret-key-change-me", "change-me", "secret"):
        raise ValueError("WEB_SESSION_SECRET is too weak/default. Please set a strong, custom random secret")

# Business settings
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Digital Store").strip()
WA_LINK = os.getenv("WA_LINK", "").strip()
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "").strip()
AUTOORDER_BOT_USERNAME = os.getenv("AUTOORDER_BOT_USERNAME", "").strip()
AUTOORDER_BOT_LINK = os.getenv("AUTOORDER_BOT_LINK", "").strip()

# Ensure directories exist
Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

logger.info("Assistant configuration loaded and directories verified.")
