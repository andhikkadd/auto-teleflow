import asyncio
import logging
import signal
import sys
from datetime import datetime

import uvicorn
import config
from database import db
from utils import state, sanitize_logs
import telegram_client
import commands
import scheduler

# Mask sensitive configurations in output
sys.stdout.write = (lambda write_orig: lambda text: write_orig(sanitize_logs(text)))(sys.stdout.write)
sys.stderr.write = (lambda write_orig: lambda text: write_orig(sanitize_logs(text)))(sys.stderr.write)

logger = logging.getLogger("Main")

# Conditional Import for FastAPI Application
if config.ENABLE_WEB_PANEL:
    from web_panel import app

async def load_settings_into_state():
    """Load persisted settings from SQLite database into global in-memory state."""
    logger.info("Loading system settings from database into memory...")
    try:
        # Load Paused State
        paused_record = await db.fetchone("SELECT value FROM settings WHERE key = 'paused'")
        if paused_record:
            state.is_paused = (paused_record["value"] == "1")
        else:
            state.is_paused = False
            
        # Load Delay Constraints
        min_delay_record = await db.fetchone("SELECT value FROM settings WHERE key = 'min_delay'")
        if min_delay_record:
            state.min_delay = int(min_delay_record["value"])
            
        max_delay_record = await db.fetchone("SELECT value FROM settings WHERE key = 'max_delay'")
        if max_delay_record:
            state.max_delay = int(max_delay_record["value"])
            
        logger.info(
            f"Runtime settings initialized: "
            f"Paused: {state.is_paused}, Delay range: {state.min_delay} - {state.max_delay} minutes."
        )
    except Exception as e:
        logger.error(f"Failed to load settings from DB: {e}. Falling back to .env values.")
        state.is_paused = False
        state.min_delay = config.DEFAULT_MIN_DELAY_MINUTES
        state.max_delay = config.DEFAULT_MAX_DELAY_MINUTES

async def main():
    logger.info("Starting Telegram Userbot Promo Framework...")
    
    # 1. Initialize SQLite Database Schema
    await db.initialize_schema()
    
    # 2. Populate In-Memory State from DB settings
    await load_settings_into_state()
    
    # 3. Start Uvicorn FastAPI Server if enabled (Do this first so panel is accessible immediately)
    web_task = None
    uvicorn_server = None
    if config.ENABLE_WEB_PANEL:
        logger.info(f"Starting FastAPI Web Control Panel on {config.WEB_HOST}:{config.WEB_PORT}...")
        uvicorn_config = uvicorn.Config(
            app=app,
            host=config.WEB_HOST,
            port=config.WEB_PORT,
            log_config=None,  # Do not override logger formatting
            log_level="warning"
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)
        web_task = asyncio.create_task(uvicorn_server.serve())
        
    # 4. Boot Telethon client (interactive console prompt if first login)
    client_started = False
    scheduler_task = None
    backup_task = None
    try:
        # We start the client connection. If it blocks or fails, we log it but keep the server running.
        me = await telegram_client.start_client()
        client_started = True
        
        # Register commands event listeners
        await commands.register_handlers()
        
        # Start scheduler background task
        scheduler_task = asyncio.create_task(scheduler.start_scheduler())
        # Start auto-backup scheduler background task
        backup_task = asyncio.create_task(scheduler.start_auto_backup_scheduler())
    except Exception as e:
        logger.error(f"Could not initialize Telegram client: {e}. Running in Web-Panel only mode.")
        logger.info("Please configure real API_ID / API_HASH and run main.py interactively to log in.")
    
    # Setup graceful shutdown handlers
    loop = asyncio.get_running_loop()
    shutdown_called = False
    
    async def shutdown():
        nonlocal shutdown_called
        if shutdown_called:
            return
        shutdown_called = True
        
        logger.info("Initiating graceful shutdown...")
        
        # Stop Web Control Panel
        if web_task and uvicorn_server:
            logger.info("Stopping Web Control Panel server...")
            uvicorn_server.should_exit = True
            try:
                await web_task
            except Exception as ex:
                logger.error(f"Error shutting down web panel: {ex}")
                
        # Cancel scheduler
        if scheduler_task:
            logger.info("Stopping background scheduler...")
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
                
        # Cancel auto-backup scheduler
        if backup_task:
            logger.info("Stopping auto-backup scheduler...")
            backup_task.cancel()
            try:
                await backup_task
            except asyncio.CancelledError:
                pass
            
        # Disconnect client
        client = telegram_client.get_client()
        if client and client.is_connected():
            logger.info("Disconnecting Telegram client...")
            await client.disconnect()
            
        # Close database connection
        db.close()
        logger.info("Shutdown completed. Exiting.")
        sys.exit(0)

    # Attach signals on platforms that support loop.add_signal_handler (UNIX / Linux VPS)
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
            except NotImplementedError:
                pass
    
    # Keep application alive while Telethon client is connected, or via web panel loop
    client = telegram_client.get_client()
    try:
        if client_started and client.is_connected():
            logger.info("Userbot is running and listening for commands 24/7.")
            await client.run_until_disconnected()
        elif web_task:
            logger.info("Web control panel is running. Keep alive loop started.")
            await web_task
        else:
            logger.info("Neither Telegram client nor Web Panel is active. Keep alive loop started.")
            while True:
                await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("System interruption received.")
    finally:
        await shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process terminated by user.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Unhandled critical crash: {e}", exc_info=True)
        sys.exit(1)
