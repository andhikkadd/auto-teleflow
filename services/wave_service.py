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
            
            # Get inter-group delay setting (min and max seconds)
            min_delay_sec_raw = await settings_svc.get_setting("delay_between_groups_min", None)
            max_delay_sec_raw = await settings_svc.get_setting("delay_between_groups_max", None)
            
            if min_delay_sec_raw is None or max_delay_sec_raw is None:
                # Fallback to the legacy single delay setting if exists
                old_delay = await settings_svc.get_setting("delay_between_groups", str(config.DELAY_BETWEEN_GROUPS_SECONDS))
                min_delay_sec_raw = old_delay
                max_delay_sec_raw = old_delay
                
            try:
                min_delay_sec = int(min_delay_sec_raw)
                max_delay_sec = int(max_delay_sec_raw)
            except ValueError:
                min_delay_sec = 15
                max_delay_sec = 30
                
            active_clients = await telegram_client.start_all_clients()
            if not active_clients:
                logger.error("No active/authorized Telegram accounts found. Wave aborted.")
                await db.execute(
                    "UPDATE wave_logs SET finished_at = ?, status = 'failed', success_count = 0, fail_count = 0 WHERE id = ?",
                    (datetime.now().isoformat(), wave_log_id)
                )
                return
            
            # Gather sender IDs for our active client accounts
            my_user_ids = []
            for c in active_clients:
                try:
                    me_obj = await c.get_me()
                    if me_obj:
                        my_user_ids.append(me_obj.id)
                except Exception as e:
                    logger.warning(f"Failed to fetch user ID for account during startup: {e}")
            
            # Divide groups among active clients
            random.shuffle(groups)
            num_clients = len(active_clients)
            partitioned_groups = [[] for _ in range(num_clients)]
            for idx, grp in enumerate(groups):
                partitioned_groups[idx % num_clients].append(grp)
            
            async def run_client_worker(client, client_groups, worker_id):
                nonlocal success_count, fail_count
                try:
                    me = await client.get_me()
                    client_name = f"{me.first_name} (@{me.username or 'NoUsername'})"
                except Exception:
                    client_name = f"Bot #{worker_id}"
                logger.info(f"Worker #{worker_id} ({client_name}) started with {len(client_groups)} groups.")
                
                # Shuffled template pool for this worker to ensure even distribution
                template_pool = []
                def get_next_template():
                    nonlocal template_pool
                    if not template_pool:
                        template_pool = [t["text"] for t in templates]
                        random.shuffle(template_pool)
                    return template_pool.pop()
                
                for idx, grp in enumerate(client_groups):
                    # Apply delay before sending (except first group)
                    if idx > 0:
                        current_delay = random.randint(min(min_delay_sec, max_delay_sec), max(min_delay_sec, max_delay_sec))
                        logger.info(f"Worker #{worker_id} ({client_name}) sleeping for {current_delay}s before next group...")
                        await asyncio.sleep(current_delay)
                        
                    target = grp["username"]
                    if target.replace("-", "").isdigit():
                        target = int(target)
                        
                    grp_id = grp["id"]
                    grp_title = grp["title"] or "No Title"
                    selected_template = get_next_template()
                    
                    try:
                        # 0. Auto-Join check: ensure bot is in the group before auditing/sending
                        from utils import resolve_target_entity
                        from telethon.tl.types import Channel
                        from telethon.tl.functions.channels import JoinChannelRequest
                        
                        entity = None
                        try:
                            entity = await client.get_entity(target)
                        except Exception:
                            try:
                                entity = await resolve_target_entity(client, target)
                            except Exception as ent_err:
                                logger.warning(f"Could not resolve entity for {grp_title} ({target}): {ent_err}")
                        
                        if entity:
                            if isinstance(entity, Channel) and getattr(entity, 'left', True):
                                logger.info(f"Account {client_name} is not in group {grp_title}. Attempting to join...")
                                try:
                                    await client(JoinChannelRequest(entity))
                                    # Human-like delay after joining to avoid Telegram anti-spam triggers
                                    join_delay = random.randint(5, 10)
                                    logger.info(f"Account {client_name} joined {grp_title}. Sleeping for {join_delay}s...")
                                    await asyncio.sleep(join_delay)
                                except Exception as join_err:
                                    logger.error(f"Account {client_name} failed to join {grp_title}: {join_err}")

                        # Ghost Auditing / Smart Deduplication check
                        ghost_auditing_enabled = await settings_svc.get_setting("ghost_auditing_enabled", "0")
                        if ghost_auditing_enabled == "1":
                            try:
                                audit_limit = int(await settings_svc.get_setting("ghost_auditing_limit", "10"))
                                audit_action = await settings_svc.get_setting("ghost_auditing_action", "skip")
                                
                                recent_messages = await client.get_messages(target, limit=audit_limit)
                                our_msg = None
                                for msg in recent_messages:
                                    if msg.sender_id in my_user_ids:
                                        our_msg = msg
                                        break
                                
                                if our_msg:
                                    if audit_action == "skip":
                                        logger.info(f"Ghost Auditing: Previous promo is still visible in the last {audit_limit} messages of {grp_title}. Skipping.")
                                        await db.execute(
                                            """
                                            INSERT INTO wave_log_items (wave_log_id, group_id, group_title, status, error_message, message_id)
                                            VALUES (?, ?, ?, 'skipped', 'Ghost Auditing: Previous promo still visible', NULL)
                                            """,
                                            (wave_log_id, grp_id, grp_title)
                                        )
                                        await db.execute(
                                            "UPDATE groups SET last_send_status = 'skipped', updated_at = ? WHERE id = ?",
                                            (datetime.now().isoformat(), grp_id)
                                        )
                                        continue
                                    elif audit_action == "delete_and_repost":
                                        logger.info(f"Ghost Auditing: Deleting previous promo message {our_msg.id} in {grp_title} before reposting.")
                                        try:
                                            await client.delete_messages(target, [our_msg.id])
                                        except Exception as del_err:
                                            logger.warning(f"Failed to delete previous message {our_msg.id}: {del_err}")
                            except Exception as audit_err:
                                logger.error(f"Error executing ghost auditing on {grp_title}: {audit_err}")

                        logger.info(f"Worker #{worker_id} ({client_name}) sending message to {grp_title} ({grp['username']})...")
                        sent_msg = await client.send_message(target, selected_template)
                        
                        # Verify message visibility post-delivery
                        is_verified = await group_svc.verify_message_delivery(grp["username"], sent_msg.id, client=client)
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
                        logger.info(f"Worker #{worker_id} ({client_name}): Message successfully sent to {grp_title} [Status: {item_status}]")
                        
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
                        logger.warning(f"Worker #{worker_id} ({client_name}) failed sending to {grp_title}: {e}")
            
            # Run all workers concurrently
            worker_tasks = []
            for i, client in enumerate(active_clients):
                if partitioned_groups[i]:
                    worker_tasks.append(run_client_worker(client, partitioned_groups[i], i + 1))
            
            if worker_tasks:
                await asyncio.gather(*worker_tasks)
                
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
            state.last_run_time = datetime.now()
            
            # 7. Dispatch Report if requested
            send_report_val = await settings_svc.get_setting("send_report", "1")
            if send_report_val == "1":
                report_target_raw = await settings_svc.get_setting("report_target", config.REPORT_TARGET)
                if report_target_raw:
                    from utils import resolve_target_entity
                    try:
                        rep_client = active_clients[0]
                        resolved_target = await resolve_target_entity(rep_client, report_target_raw)
                        duration_sec = (datetime.fromisoformat(finished_str) - datetime.fromisoformat(now_str)).total_seconds()
                        report_msg = (
                            f"📊 **Laporan Pengiriman Wave #{wave_log_id}**\n"
                            f"• **Pemicu**: `{triggered_by}`\n"
                            f"• **Waktu Mulai**: `{now_str}`\n"
                            f"• **Durasi**: `{duration_sec:.1f} detik`\n"
                            f"• **Hasil**: `{success_count} Sukses` / `{fail_count} Gagal`\n"
                            f"• **Jumlah Akun Aktif**: `{len(active_clients)}`"
                        )
                        await rep_client.send_message(resolved_target, report_msg)
                        logger.info(f"Wave delivery report sent successfully to {report_target_raw}.")
                    except Exception as rep_err:
                        logger.error(f"Failed to send wave report to {report_target_raw}: {rep_err}")
                        
        finally:
            # Release lock
            state.active_wave_task = None
            
wave_svc = WaveService()
