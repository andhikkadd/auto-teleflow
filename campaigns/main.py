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
    
    # 3. Boot Telethon client (interactive console prompt if first login)
    me = await telegram_client.start_client()
    
    # 4. Register commands event listeners
    await commands.register_handlers()
    
    # 5. Start scheduler background task
    scheduler_task = asyncio.create_task(scheduler.start_scheduler())
    
    # 6. Start Uvicorn FastAPI Server if enabled
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
        logger.info("Stopping background scheduler...")
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
            
        # Disconnect client
        client = telegram_client.get_client()
        if client.is_connected():
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
    
    # Keep application alive while Telethon client is connected
    client = telegram_client.get_client()
    try:
        logger.info("Userbot is running and listening for commands 24/7.")
        await client.run_until_disconnected()
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
