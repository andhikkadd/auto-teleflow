import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from root .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Setup logging config temporarily before log level is loaded
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("Config")

def parse_bool(value) -> bool:
    if not value:
        return False
    return str(value).lower() in ("true", "1", "yes", "on")

# Required Credentials
API_ID_RAW = os.getenv("API_ID")
if not API_ID_RAW:
    raise ValueError("API_ID is required but missing in .env")
try:
    API_ID = int(API_ID_RAW)
except ValueError:
    raise ValueError("API_ID must be an integer")

API_HASH = os.getenv("API_HASH")
if not API_HASH:
    raise ValueError("API_HASH is required but missing in .env")

# Session Config
SESSION_NAME = os.getenv("SESSION_NAME", "sessions/promo_userbot")

# Master / Authorization Settings
MASTER_USERNAME = os.getenv("MASTER_USERNAME", "").strip().lstrip("@")
MASTER_ID_RAW = os.getenv("MASTER_ID")
MASTER_ID = None
if MASTER_ID_RAW and MASTER_ID_RAW.strip():
    try:
        MASTER_ID = int(MASTER_ID_RAW.strip())
    except ValueError:
        logger.warning("MASTER_ID must be an integer if set. Ignoring MASTER_ID, falling back to MASTER_USERNAME.")

if not MASTER_USERNAME and not MASTER_ID:
    raise ValueError("Either MASTER_USERNAME or MASTER_ID must be specified in .env")

# Report & Backup Target Configuration
def _resolve_target(val: str) -> str:
    cleaned = val.strip()
    if cleaned.lower() == "me":
        return "me"
    if cleaned.replace("-", "").isdigit():
        return int(cleaned)
    return cleaned

REPORT_TARGET = _resolve_target(os.getenv("REPORT_TARGET", "me"))
BACKUP_TARGET = _resolve_target(os.getenv("BACKUP_TARGET", "me"))
BACKUP_PASSWORD = os.getenv("BACKUP_PASSWORD", "").strip()

if not REPORT_TARGET:
    raise ValueError("REPORT_TARGET is required and cannot be empty")
if not BACKUP_TARGET:
    raise ValueError("BACKUP_TARGET is required and cannot be empty")

SEND_REPORT = parse_bool(os.getenv("SEND_REPORT", "true"))
RUN_WAVE_ON_START = parse_bool(os.getenv("RUN_WAVE_ON_START", "false"))

# Wave Delay Configuration (Ensure safe integers and defaults)
try:
    DEFAULT_MIN_DELAY_MINUTES = int(os.getenv("DEFAULT_MIN_DELAY_MINUTES", "60"))
except ValueError:
    DEFAULT_MIN_DELAY_MINUTES = 60

try:
    DEFAULT_MAX_DELAY_MINUTES = int(os.getenv("DEFAULT_MAX_DELAY_MINUTES", "180"))
except ValueError:
    DEFAULT_MAX_DELAY_MINUTES = 180

if DEFAULT_MIN_DELAY_MINUTES < 1:
    raise ValueError("DEFAULT_MIN_DELAY_MINUTES must be >= 1")
if DEFAULT_MAX_DELAY_MINUTES <= DEFAULT_MIN_DELAY_MINUTES:
    raise ValueError("DEFAULT_MAX_DELAY_MINUTES must be strictly greater than DEFAULT_MIN_DELAY_MINUTES")

try:
    DELAY_BETWEEN_GROUPS_SECONDS = int(os.getenv("DELAY_BETWEEN_GROUPS_SECONDS", "15"))
except ValueError:
    DELAY_BETWEEN_GROUPS_SECONDS = 15

if DELAY_BETWEEN_GROUPS_SECONDS < 1:
    raise ValueError("DELAY_BETWEEN_GROUPS_SECONDS must be >= 1")

# Backup Configuration
ALLOW_UNENCRYPTED_BACKUP = parse_bool(os.getenv("ALLOW_UNENCRYPTED_BACKUP", "false"))
BACKUP_INCLUDE_ENV = parse_bool(os.getenv("BACKUP_INCLUDE_ENV", "false"))
DELETE_LOCAL_BACKUP_AFTER_SEND = parse_bool(os.getenv("DELETE_LOCAL_BACKUP_AFTER_SEND", "true"))

# Database path
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/bot.db")

# Log Settings
LOG_LEVEL_RAW = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_RAW, logging.INFO)

# Web Panel Configuration
ENABLE_WEB_PANEL = parse_bool(os.getenv("ENABLE_WEB_PANEL", "true"))
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1").strip()  # Default to localhost for secure access via CF Tunnel
try:
    WEB_PORT = int(os.getenv("WEB_PORT", "8000"))
except ValueError:
    WEB_PORT = 8000

WEB_ADMIN_USERNAME = os.getenv("WEB_ADMIN_USERNAME", "admin").strip()
WEB_ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "").strip()
WEB_SESSION_SECRET = os.getenv("WEB_SESSION_SECRET", "").strip()
WEB_TRUST_PROXY = parse_bool(os.getenv("WEB_TRUST_PROXY", "false"))

if ENABLE_WEB_PANEL:
    if not WEB_ADMIN_PASSWORD:
        raise ValueError("WEB_ADMIN_PASSWORD is required in .env when ENABLE_WEB_PANEL is enabled")
    if WEB_ADMIN_PASSWORD.lower() in ("admin", "password", "123456", "12345678", "root", "qwerty"):
        raise ValueError("WEB_ADMIN_PASSWORD is too weak/default. Please set a strong, custom password in .env")
    if WEB_ADMIN_USERNAME.lower() in ("admin", "root") and WEB_ADMIN_PASSWORD.lower() == WEB_ADMIN_USERNAME.lower():
        raise ValueError("WEB_ADMIN_PASSWORD cannot be the same as WEB_ADMIN_USERNAME")
        
    if not WEB_SESSION_SECRET:
        raise ValueError("WEB_SESSION_SECRET is required in .env when ENABLE_WEB_PANEL is enabled")
    if WEB_SESSION_SECRET.lower() in ("secret-key-change-me", "change-me", "secret"):
        raise ValueError("WEB_SESSION_SECRET is too weak/default. Please set a strong, custom random secret in .env")

# Make sure directory structures exist
Path(SESSION_NAME).parent.mkdir(parents=True, exist_ok=True)
Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
Path("backups").mkdir(parents=True, exist_ok=True)

# Re-configure logging with correct level
logging.getLogger().setLevel(LOG_LEVEL)
logger.info("Configuration successfully loaded and directories validated.")
