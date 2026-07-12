import os
import logging
import asyncio
from pathlib import Path
from telethon import TelegramClient
import config

logger = logging.getLogger("TelegramClient")

# Map of session name (str) to TelegramClient instance
_clients = {}

# Pending login flows (in-memory cache for web OTP submission)
# Format: {phone_number: {"client": TelegramClient, "phone_code_hash": str, "created_at": datetime}}
pending_logins = {}

def get_clients_dict() -> dict:
    """Get the dictionary of all loaded clients."""
    return _clients

def get_session_files() -> list[str]:
    """Retrieve all .session file names (without extension) from sessions folder."""
    sess_dir = Path("sessions")
    sess_dir.mkdir(parents=True, exist_ok=True)
    sessions = []
    
    # Always scan the directory for session files
    for f in sess_dir.glob("*.session"):
        # Skip journal/temporary files
        if f.name.endswith(".session-journal"):
            continue
        sessions.append(f.stem)
        
    # Always include the default session name if it has a file
    default_stem = Path(config.SESSION_NAME).stem
    if default_stem not in sessions and (sess_dir / f"{default_stem}.session").exists():
        sessions.append(default_stem)
        
    # Fallback to default session if directory is empty
    if not sessions:
        sessions.append(default_stem)
        
    return sorted(list(set(sessions)))

def get_proxy_for_session(session_name: str) -> str:
    """Retrieve proxy URL from database for a specific session."""
    from database import db
    if not db.conn:
        db.connect()
    try:
        cursor = db.conn.cursor()
        cursor.execute("SELECT proxy_url FROM session_proxies WHERE session_name = ?", (session_name,))
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
    except Exception as e:
        logger.error(f"Error reading proxy for session {session_name}: {e}")
        return None

def parse_proxy_url(proxy_url: str):
    """Parse a proxy URL into Telethon-compatible socks proxy tuple."""
    if not proxy_url:
        return None
    from urllib.parse import urlparse
    try:
        import socks
        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        if scheme == 'socks5':
            proxy_type = socks.SOCKS5
        elif scheme == 'socks4':
            proxy_type = socks.SOCKS4
        elif scheme in ('http', 'https'):
            proxy_type = socks.HTTP
        else:
            return None
        
        return (
            proxy_type,
            parsed.hostname,
            parsed.port or (1080 if 'socks' in scheme else 80),
            True,
            parsed.username,
            parsed.password
        )
    except ImportError:
        logger.error("PySocks module is not installed. Please run 'pip install PySocks' to enable proxy support.")
        raise RuntimeError("Library 'PySocks' tidak terinstal di server. Silakan jalankan 'pip install PySocks' di VPS Anda.")
    except Exception as e:
        logger.error(f"Error parsing proxy URL '{proxy_url}': {e}")
        return None

def get_client(session_name: str = None) -> TelegramClient:
    """
    Get or create a TelegramClient instance for a specific session name.
    If session_name is None, returns the first available active client, or the default.
    """
    global _clients
    if session_name is None:
        active = [c for name, c in list(_clients.items()) if c.is_connected() and is_session_active(name)]
        if active:
            return active[0]
        any_connected = [c for c in _clients.values() if c.is_connected()]
        if any_connected:
            return any_connected[0]
        # Fallback to default session
        session_name = Path(config.SESSION_NAME).stem

    if session_name not in _clients:
        session_path = os.path.join("sessions", session_name)
        proxy_url = get_proxy_for_session(session_name)
        proxy_config = parse_proxy_url(proxy_url)
        if proxy_config:
            # Mask credentials in logs
            log_url = proxy_url
            if '@' in proxy_url:
                parts = proxy_url.split('@', 1)
                scheme_part = parts[0].split('//', 1)
                log_url = f"{scheme_part[0]}//***:***@{parts[1]}"
            logger.info(f"Session '{session_name}' using proxy: {log_url}")
            
        import sqlite3
        try:
            _clients[session_name] = TelegramClient(
                session_path,
                config.API_ID,
                config.API_HASH,
                connection_retries=10,
                retry_delay=5,
                proxy=proxy_config
            )
        except sqlite3.DatabaseError as db_err:
            if "malformed" in str(db_err).lower():
                logger.error(f"Database session file '{session_path}.session' is malformed/corrupted. Renaming and recreating...")
                try:
                    p = Path(f"{session_path}.session")
                    if p.exists():
                        corrupt_p = Path(f"{session_path}.session.corrupted")
                        if corrupt_p.exists():
                            corrupt_p.unlink()
                        p.rename(corrupt_p)
                except Exception as rename_err:
                    logger.error(f"Failed to rename malformed session file: {rename_err}")
                
                # Retry with clean/re-created session
                _clients[session_name] = TelegramClient(
                    session_path,
                    config.API_ID,
                    config.API_HASH,
                    connection_retries=10,
                    retry_delay=5,
                    proxy=proxy_config
                )
            else:
                raise
    return _clients[session_name]

def is_session_active(session_name: str) -> bool:
    """Check if a session is enabled in the database."""
    from database import db
    if not db.conn:
        db.connect()
    try:
        cursor = db.conn.cursor()
        cursor.execute("SELECT is_active FROM session_proxies WHERE session_name = ?", (session_name,))
        row = cursor.fetchone()
        return row["is_active"] != 0 if row and row["is_active"] is not None else True
    except Exception:
        return True

def get_active_clients() -> list[TelegramClient]:
    """Return a list of all currently authorized/active and enabled TelegramClient instances."""
    active_clients = []
    for name, client in list(_clients.items()):
        if client.is_connected() and is_session_active(name):
            active_clients.append(client)
    return active_clients

async def start_all_clients() -> list[TelegramClient]:
    """Start all clients for session files found in the sessions directory."""
    session_names = get_session_files()
    logger.info(f"Found session files to load: {session_names}")
    
    active_clients = []
    for name in session_names:
        if not is_session_active(name):
            logger.info(f"Client '{name}' is deactivated in database. Skipping connection.")
            continue
            
        try:
            client = get_client(name)
            logger.info(f"Connecting client for session: {name}...")
            await client.connect()
            if not await client.is_user_authorized():
                logger.warning(f"Client session '{name}' is NOT authorized. Skipping...")
                continue
            
            me = await client.get_me()
            logger.info(f"Client '{name}' successfully authorized as {me.first_name} (@{me.username or 'NoUsername'})")
            # Cache dialogs for entity resolution
            await client.get_dialogs()
            active_clients.append(client)
        except Exception as e:
            logger.error(f"Failed to start client for session '{name}': {e}")
            
    return active_clients

async def start_client() -> TelegramClient:
    """Legacy helper to start the default client connection."""
    clients = await start_all_clients()
    if clients:
        return clients[0]
    # If no clients loaded/authorized, return default client to keep legacy interface compatible
    default_name = Path(config.SESSION_NAME).stem
    return get_client(default_name)

async def disconnect_all_clients():
    """Disconnect all active client connections."""
    global _clients
    for name, client in list(_clients.items()):
        if client.is_connected():
            logger.info(f"Disconnecting client: {name}...")
            await client.disconnect()
    _clients.clear()
