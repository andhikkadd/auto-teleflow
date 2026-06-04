import asyncio
import logging
import sys

import config
from database import db
from bot import start_bot

logger = logging.getLogger("Main")

async def main():
    logger.info("Initializing Auto-Teleflow Assistant Application...")
    
    # 1. Initialize SQLite connection and database schema
    await db.initialize()
    
    tasks = []
    
    # 2. Add Telegram Bot Task
    tasks.append(start_bot())
    
    # 3. Add Web Panel Task (if enabled)
    if config.ENABLE_WEB_PANEL:
        from web_panel import run_server
        tasks.append(run_server())
    else:
        logger.info("Web panel is disabled via ENABLE_WEB_PANEL.")
        
    try:
        # Run tasks concurrently in the running loop
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application shutdown triggered.")
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user.")
        sys.exit(0)
