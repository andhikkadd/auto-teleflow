import logging
import asyncio
from telethon import TelegramClient
import config

logger = logging.getLogger("TelegramClient")

_client = None

def get_client() -> TelegramClient:
    """Get the singleton TelegramClient instance."""
    global _client
    if _client is None:
        # Resolve the session name path
        _client = TelegramClient(
            config.SESSION_NAME,
            config.API_ID,
            config.API_HASH,
            connection_retries=10,
            retry_delay=5
        )
    return _client

async def start_client():
    """Start the Telegram client and handle interactive login if necessary."""
    client = get_client()
    logger.info("Connecting to Telegram...")
    await client.connect()

    if not await client.is_user_authorized():
        logger.info("User is not authorized. Interactive console login is starting...")
        # Start will prompt for phone number and OTP on the terminal/console
        # it is fully async and robust in Telethon v1.x
        await client.start()
    
    me = await client.get_me()
    logger.info(f"Userbot successfully logged in as: {me.first_name} (@{me.username or 'NoUsername'})")
    
    logger.info("Caching Telegram dialogs for entity resolution...")
    await client.get_dialogs()
    logger.info("Dialog caching complete.")
    
    return me

