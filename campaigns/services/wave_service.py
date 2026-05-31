import logging
import asyncio
import random
from datetime import datetime

from database import db
from utils import state
import telegram_client
from services.group_service import group_svc
from services.template_service import template_svc
from services.settings_service import settings_svc
import config

logger = logging.getLogger("WaveService")

class WaveService:
    @staticmethod
    async def run_wave(triggered_by: str):
        """Execute a promotional wave. Protected by an anti-double-wave lock."""
        # 1. Enforce anti-overlapping lock
        if state.active_wave_task is not None:
            logger.warning("Another wave execution task is already running. Skipping trigger.")
            return
            
        state.active_wave_task = asyncio.current_task()
        logger.info(f"Starting wave triggered by: {triggered_by}")
        
        try:
            # 2. Get active templates
            templates = await template_svc.get_active_templates()
            if not templates:
                logger.error("No active promotion templates found. Wave aborted.")
                # Send emergency error if target is configured
                return
                
            selected_template = random.choice(templates)["text"]
            
            # 3. Get active target groups that are not in cooldown
            now_iso = datetime.now().isoformat()
            groups = await db.fetchall(
                """
                SELECT * FROM groups 
                WHERE is_skipped = 0 
                  AND status IN ('ACTIVE', 'UNVERIFIED') 
                  AND (cooldown_until IS NULL OR cooldown_until <= ?)
                """,
                (now_iso,)
            )
            
            if not groups:
                logger.info("No active, non-cooldown target groups available for this wave.")
                state.last_run_time = datetime.now()
                return
                
            # 4. Insert wave log row
            now_str = datetime.now().isoformat()
            wave_log_id = await db.execute(
                """
                INSERT INTO wave_logs (started_at, finished_at, status, success_count, fail_count)
                VALUES (?, NULL, 'running', 0, 0)
                """,
                (now_str,)
            )
            
            success_count = 0
            fail_count = 0
            
            # Get inter-group delay setting
            delay_sec_raw = await settings_svc.get_setting("delay_between_groups", str(config.DELAY_BETWEEN_GROUPS_SECONDS))
            try:
                delay_sec = int(delay_sec_raw)
            except ValueError:
                delay_sec = 15
                
            client = telegram_client.get_client()
            
            # 5. Delivery Loop
            for idx, grp in enumerate(groups):
                # Apply inter-group delay (except for first target)
                if idx > 0:
                    await asyncio.sleep(delay_sec)
                    
                target = grp["username"]
                # Convert numeric strings (Telegram peer IDs) back to integers
                if target.replace("-", "").isdigit():
                    target = int(target)
                    
                grp_id = grp["id"]
                grp_title = grp["title"] or "No Title"
                
                try:
                    sent_msg = await client.send_message(target, selected_template)
                    
                    # Verify message visibility post-delivery
                    is_verified = await group_svc.verify_message_delivery(grp["username"], sent_msg.id)
                    item_status = "success" if is_verified else "unverified"
                    grp_status = "ACTIVE" if is_verified else "UNVERIFIED"
                    
                    # Update database group health record
                    await db.execute(
                        """
                        UPDATE groups 
                        SET status = ?, last_send_status = ?, last_success_at = ?, 
                            fail_streak = 0, last_error = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (grp_status, item_status, datetime.now().isoformat(), datetime.now().isoformat(), grp_id)
                    )
                    
                    # Insert wave log details
                    await db.execute(
                        """
                        INSERT INTO wave_log_items (wave_log_id, group_id, group_title, status, error_message, message_id)
                        VALUES (?, ?, ?, ?, NULL, ?)
                        """,
                        (wave_log_id, grp_id, grp_title, item_status, sent_msg.id)
                    )
                    
                    success_count += 1
                    logger.info(f"Message successfully sent to {grp_title} ({grp['username']}) [Status: {item_status}]")
                    
                except Exception as e:
                    # Update DB health properties based on exception mapping
                    await group_svc.handle_delivery_error(grp_id, e)
                    
                    # Log failure to wave log items
                    await db.execute(
                        """
                        INSERT INTO wave_log_items (wave_log_id, group_id, group_title, status, error_message, message_id)
                        VALUES (?, ?, ?, 'failed', ?, NULL)
                        """,
                        (wave_log_id, grp_id, grp_title, str(e))
                    )
                    
                    fail_count += 1
                    logger.warning(f"Failed to deliver message to {grp_title} ({grp['username']}): {e}")
                    
            # 6. Complete Wave Log
            finished_str = datetime.now().isoformat()
            await db.execute(
                """
                UPDATE wave_logs 
                SET finished_at = ?, status = 'completed', success_count = ?, fail_count = ?
                WHERE id = ?
                """,
                (finished_str, success_count, fail_count, wave_log_id)
            )
            
            logger.info(f"Wave execution finished: {success_count} success, {fail_count} failed.")
            
            # Update live stats
            state.last_run_time = datetime.now()
            
            # 7. Dispatch Report if requested
            send_report_val = await settings_svc.get_setting("send_report", "1")
            if send_report_val == "1":
                report_target = await settings_svc.get_setting("report_target", config.REPORT_TARGET)
                if report_target:
                    # Cast to int if numeric string (e.g. numeric ID)
                    if isinstance(report_target, str):
                        cleaned_tgt = report_target.strip()
                        if cleaned_tgt.replace("-", "").isdigit():
                            report_target = int(cleaned_tgt)
                            
                    duration_sec = (datetime.fromisoformat(finished_str) - datetime.fromisoformat(now_str)).total_seconds()
                    report_msg = (
                        f"📊 **Laporan Pengiriman Wave #{wave_log_id}**\n"
                        f"• **Pemicu**: `{triggered_by}`\n"
                        f"• **Waktu Mulai**: `{now_str}`\n"
                        f"• **Durasi**: `{duration_sec:.1f} detik`\n"
                        f"• **Hasil**: `{success_count} Sukses` / `{fail_count} Gagal`"
                    )
                    try:
                        await client.send_message(report_target, report_msg)
                        logger.info(f"Wave delivery report sent successfully to {report_target}.")
                    except Exception as rep_err:
                        logger.error(f"Failed to send wave report to {report_target}: {rep_err}")
                        
        finally:
            # Release lock
            state.active_wave_task = None
            
wave_svc = WaveService()
