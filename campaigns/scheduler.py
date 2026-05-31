import asyncio
import logging
import random
from datetime import datetime, timedelta
from utils import state
import config
from services.wave_service import wave_svc
from services.settings_service import settings_svc

logger = logging.getLogger("Scheduler")

async def start_scheduler():
    """Initializes and runs the scheduler loop."""
    logger.info("Initializing background scheduler...")
    
    try:
        # Load delay constraints, paused, and run_on_start from database settings on startup
        paused_val = await settings_svc.get_setting("paused", "0")
        state.is_paused = (paused_val == "1")
        
        min_val = await settings_svc.get_setting("min_delay", str(config.DEFAULT_MIN_DELAY_MINUTES))
        state.min_delay = int(min_val)
        
        max_val = await settings_svc.get_setting("max_delay", str(config.DEFAULT_MAX_DELAY_MINUTES))
        state.max_delay = int(max_val)
        
        run_start_val = await settings_svc.get_setting("run_wave_on_start", "0")
        run_on_start = (run_start_val == "1")
        
    except Exception as e:
        logger.error(f"Failed to load scheduler settings from database: {e}. Using defaults.")
        state.is_paused = False
        state.min_delay = config.DEFAULT_MIN_DELAY_MINUTES
        state.max_delay = config.DEFAULT_MAX_DELAY_MINUTES
        run_on_start = config.RUN_WAVE_ON_START

    # Run wave on startup if configured and bot is not paused
    if run_on_start:
        if not state.is_paused:
            logger.info("run_wave_on_start is enabled. Queueing initial startup wave...")
            asyncio.create_task(wave_svc.run_wave("Startup Trigger"))
        else:
            logger.info("run_wave_on_start is enabled, but scheduler is PAUSED. Startup wave skipped.")

    # Main scheduler loop
    while True:
        try:
            if state.is_paused:
                state.next_run_time = None
                await asyncio.sleep(5)
                continue

            # Calculate next delay interval
            delay_minutes = random.randint(state.min_delay, state.max_delay)
            state.next_run_time = datetime.now() + timedelta(minutes=delay_minutes)
            logger.info(f"Next wave scheduled at {state.next_run_time.strftime('%Y-%m-%d %H:%M:%S')} (in {delay_minutes} minutes)")

            # Sleep responsively
            while datetime.now() < state.next_run_time:
                if state.is_paused:
                    logger.info("Scheduler paused during delay sleep cycle. Resetting schedule.")
                    state.next_run_time = None
                    break
                await asyncio.sleep(5)

            # Check again before running to prevent running while paused
            if not state.is_paused and state.next_run_time and datetime.now() >= state.next_run_time:
                logger.info("Scheduled time reached. Triggering scheduled wave...")
                await wave_svc.run_wave("Auto Scheduler")

        except asyncio.CancelledError:
            logger.info("Scheduler task cancelled.")
            break
        except Exception as e:
            logger.exception(f"Unexpected error in scheduler loop: {e}")
            await asyncio.sleep(30)
