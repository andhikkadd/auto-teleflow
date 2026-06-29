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

def get_client(session_name: str = None) -> TelegramClient:
    """
    Get or create a TelegramClient instance for a specific session name.
    If session_name is None, returns the first available active client, or the default.
    """
    global _clients
    if session_name is None:
        active = [c for c in _clients.values() if c.is_connected()]
        if active:
            return active[0]
        # Fallback to default session
        session_name = Path(config.SESSION_NAME).stem

    if session_name not in _clients:
        session_path = os.path.join("sessions", session_name)
        _clients[session_name] = TelegramClient(
            session_path,
            config.API_ID,
            config.API_HASH,
            connection_retries=10,
            retry_delay=5
        )
    return _clients[session_name]

def get_active_clients() -> list[TelegramClient]:
    """Return a list of all currently authorized/active TelegramClient instances."""
    return [c for c in _clients.values() if c.is_connected()]

async def start_all_clients() -> list[TelegramClient]:
    """Start all clients for session files found in the sessions directory."""
    session_names = get_session_files()
    logger.info(f"Found session files to load: {session_names}")
    
    active_clients = []
    for name in session_names:
        client = get_client(name)
        try:
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
