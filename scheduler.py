import asyncio
import logging
import random
import os
from datetime import datetime, timedelta
from utils import state
import config
from services.wave_service import wave_svc
from services.settings_service import settings_svc
import telegram_client

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

            # Human Mode Sleep Cycle check
            try:
                human_mode = await settings_svc.get_setting("human_mode_enabled", "0")
                if human_mode == "1":
                    sleep_start = await settings_svc.get_setting("human_mode_sleep_start", "23:00")
                    sleep_end = await settings_svc.get_setting("human_mode_sleep_end", "06:00")
                    
                    now = datetime.now()
                    start_parts = sleep_start.split(":")
                    end_parts = sleep_end.split(":")
                    
                    if len(start_parts) == 2 and len(end_parts) == 2:
                        start_h, start_m = int(start_parts[0]), int(start_parts[1])
                        end_h, end_m = int(end_parts[0]), int(end_parts[1])
                        
                        start_time = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
                        end_time = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
                        
                        is_sleep_time = False
                        if start_time <= end_time:
                            is_sleep_time = start_time <= now <= end_time
                        else:
                            is_sleep_time = now >= start_time or now <= end_time
                            
                        if is_sleep_time:
                            if now <= end_time:
                                wakeup_time = end_time
                            else:
                                wakeup_time = end_time + timedelta(days=1)
                            
                            state.next_run_time = wakeup_time
                            logger.info(f"Human Mode Enabled: Currently in sleep hours ({sleep_start} - {sleep_end}). Scheduler will sleep until {state.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as human_err:
                logger.error(f"Error checking Human Mode in scheduler: {human_err}")

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

async def start_auto_backup_scheduler():
    """Background task to run automatic backups every 2 days."""
    logger.info("Initializing auto-backup scheduler (every 2 days)...")
    
    # Wait 5 minutes after startup before the first check
    await asyncio.sleep(300)
    
    while True:
        try:
            client = telegram_client.get_client()
            if not client or not client.is_connected() or not await client.is_user_authorized():
                await asyncio.sleep(60)
                continue
                
            last_backup_str = await settings_svc.get_setting("last_auto_backup_time", "")
            
            run_backup = False
            if not last_backup_str:
                run_backup = True
            else:
                try:
                    last_backup_dt = datetime.fromisoformat(last_backup_str)
                    if datetime.now() - last_backup_dt >= timedelta(days=2):
                        run_backup = True
                except Exception:
                    run_backup = True
                    
            if run_backup:
                logger.info("Triggering scheduled automatic backup...")
                from services.backup_service import backup_svc
                
                backup_paths = await backup_svc.create_backup()
                
                report_target_raw = await settings_svc.get_setting("report_target", config.REPORT_TARGET)
                if report_target_raw:
                    from utils import resolve_target_entity
                    resolved_target = await resolve_target_entity(client, report_target_raw)
                    for path in backup_paths:
                        caption_msg = (
                            f"🔒 **Auto-Backup (2 Harian)**\n"
                            f"• **Waktu**: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                            f"• **Berkas**: `{os.path.basename(path)}`"
                        )
                        await client.send_file(resolved_target, path, caption=caption_msg)
                        backup_svc.clean_backup_file(path)
                    logger.info(f"Auto-backup successfully sent to {report_target_raw}")
                else:
                    logger.warning("Auto-backup skipped: report_target settings is empty.")
                    for path in backup_paths:
                        backup_svc.clean_backup_file(path)
                    
                await settings_svc.set_setting("last_auto_backup_time", datetime.now().isoformat())
                
        except asyncio.CancelledError:
            logger.info("Auto-backup scheduler cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in auto-backup scheduler loop: {e}", exc_info=True)
            
        # Check every 1 hour
        await asyncio.sleep(3600)

