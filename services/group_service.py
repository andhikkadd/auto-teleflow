import logging
from datetime import datetime, timedelta
import asyncio

from database import db
from utils import state, resolve_target_entity
import telegram_client

# Telethon Errors
from telethon.errors import (
    RPCError,
    FloodWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    ChannelPrivateError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    SlowModeWaitError,
    ChatAdminRequiredError
)

logger = logging.getLogger("GroupService")

def clean_username_input(raw_input: str) -> str:
    """Clean group join links or URLs into standard usernames/entities."""
    cleaned = raw_input.strip()
    if not cleaned:
        return ""
    # Remove URL prefixes
    cleaned = cleaned.replace("https://t.me/", "")
    cleaned = cleaned.replace("http://t.me/", "")
    cleaned = cleaned.replace("t.me/", "")
    cleaned = cleaned.replace("https://telegram.me/", "")
    cleaned = cleaned.replace("telegram.me/", "")
    if cleaned.startswith("joinchat/") or cleaned.startswith("+"):
        # This is a private invite link (hash), do not prepend @ or process as regular path
        pass
    else:
        # Prepend @ if it's a clean username and doesn't start with it or isn't a numeric ID
        if not cleaned.startswith("@") and not cleaned.replace("-", "").isdigit():
            cleaned = "@" + cleaned
            
    # Enforce lowercase for usernames to prevent duplicates due to case mismatch
    if cleaned.startswith("@"):
        cleaned = cleaned.lower()
        
    return cleaned

class GroupService:
    @staticmethod
    async def get_all_groups() -> list:
        return await db.fetchall("SELECT * FROM groups ORDER BY id ASC")

    @staticmethod
    async def get_group(group_id: int) -> dict:
        return await db.fetchone("SELECT * FROM groups WHERE id = ?", (group_id,))

    @staticmethod
    async def get_group_by_ref(ref: str) -> dict:
        """Find group by ID (as int) or username (as string)."""
        is_id = False
        db_id = None
        ref_check = ref
        if ref_check.startswith("-"):
            ref_check = ref_check[1:]
        if ref_check.isdigit():
            is_id = True
            db_id = int(ref)
            
        if is_id:
            group = await db.fetchone("SELECT * FROM groups WHERE id = ?", (db_id,))
            if not group:
                group = await db.fetchone("SELECT * FROM groups WHERE peer_id = ?", (db_id,))
            if not group:
                group = await db.fetchone("SELECT * FROM groups WHERE username = ?", (str(db_id),))
            return group
        else:
            clean_target = clean_username_input(ref)
            group = await db.fetchone("SELECT * FROM groups WHERE username = ?", (clean_target,))
            if not group:
                group = await db.fetchone("SELECT * FROM groups WHERE raw_input = ?", (ref,))
            return group

    @staticmethod
    async def add_group(raw_input: str, client=None) -> dict:
        """Resolve group entity via Telethon and add to database."""
        if not raw_input or not raw_input.strip():
            raise ValueError("Input username/link is invalid.")
        clean_target = clean_username_input(raw_input)
        if not clean_target:
            raise ValueError("Input username/link is invalid.")
            
        # Input validation: Target must look like @username, t.me/username, invite link, or numeric ID
        import re
        target_check = clean_target.lstrip("@")
        if not re.match(r'^[a-zA-Z0-9_]{3,32}$', target_check):
            # Check if it's a join link path or phone number / digits
            if not (clean_target.startswith("joinchat/") or clean_target.startswith("+") or clean_target.replace("-", "").isdigit()):
                raise ValueError("Group username/link is invalid. Must be @username, invite link, or numeric ID.")
                
        # Check if already exists in DB
        existing = await db.fetchone("SELECT * FROM groups WHERE username = ?", (clean_target,))
        if existing:
            return {"status": "exists", "group": existing}

        if client is None:
            client = telegram_client.get_client()
        try:
            invite_hash = None
            if clean_target.startswith("joinchat/"):
                invite_hash = clean_target.split("/")[-1]
            elif clean_target.startswith("+"):
                invite_hash = clean_target[1:]

            entity = None
            if invite_hash:
                from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
                from telethon.errors import UserAlreadyParticipantError
                try:
                    updates = await client(ImportChatInviteRequest(invite_hash))
                    if hasattr(updates, "chats") and updates.chats:
                        entity = updates.chats[0]
                    else:
                        invite_info = await client(CheckChatInviteRequest(invite_hash))
                        if hasattr(invite_info, "chat"):
                            entity = invite_info.chat
                except UserAlreadyParticipantError:
                    invite_info = await client(CheckChatInviteRequest(invite_hash))
                    if hasattr(invite_info, "chat"):
                        entity = invite_info.chat

            if not entity:
                entity = await client.get_entity(clean_target)
                
            # Automatically join the group/channel if it is a public channel/supergroup and we are not in it
            from telethon.tl.types import Channel
            from telethon.tl.functions.channels import JoinChannelRequest
            if isinstance(entity, Channel):
                if getattr(entity, 'left', True):
                    logger.info(f"Userbot is not in public group/channel {clean_target}. Attempting to join...")
                    await client(JoinChannelRequest(entity))
                    # Refresh the entity after joining to get updated info (e.g. left=False)
                    entity = await client.get_entity(entity)
                
            title = getattr(entity, "title", "No Title")
            
            from telethon.utils import get_peer_id
            # If the entity has a username, store it. Otherwise, store the signed peer ID.
            if getattr(entity, "username", None):
                db_username = "@" + entity.username.lower()
            else:
                db_username = str(get_peer_id(entity))
                
            # Check by peer_id to prevent duplicates
            from telethon.utils import get_peer_id
            try:
                peer_id = get_peer_id(entity)
            except Exception:
                peer_id = getattr(entity, 'id', None)

            if peer_id is not None:
                existing_peer = await db.fetchone("SELECT * FROM groups WHERE peer_id = ?", (peer_id,))
                if existing_peer:
                    return {"status": "exists", "group": existing_peer}
            
            # Double check with resolved username/ID to avoid duplicates
            existing_resolved = await db.fetchone("SELECT * FROM groups WHERE username = ?", (db_username,))
            if existing_resolved:
                return {"status": "exists", "group": existing_resolved}
                
            now_str = state.get_target_now().isoformat()
            
            group_db_id = await db.execute(
                """
                INSERT INTO groups (peer_id, username, title, raw_input, is_skipped, status, fail_streak, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, 'ACTIVE', 0, ?, ?)
                """,
                (peer_id, db_username, title, raw_input, now_str, now_str)
            )
            
            new_group = await db.fetchone("SELECT * FROM groups WHERE id = ?", (group_db_id,))
            return {"status": "added", "group": new_group}
            
        except Exception as e:
            logger.error(f"Failed to resolve group {clean_target}: {e}")
            raise

    @staticmethod
    async def delete_group(group_id: int):
        await db.execute("DELETE FROM groups WHERE id = ?", (group_id,))

    @staticmethod
    async def set_skip(group_id: int, skip: bool):
        now_str = state.get_target_now().isoformat()
        status_val = "SKIPPED" if skip else "ACTIVE"
        is_skipped_val = 1 if skip else 0
        await db.execute(
            "UPDATE groups SET is_skipped = ?, status = ?, updated_at = ? WHERE id = ?",
            (is_skipped_val, status_val, now_str, group_id)
        )

    @staticmethod
    async def reset_group(group_id: int):
        now_str = state.get_target_now().isoformat()
        await db.execute(
            """
            UPDATE groups 
            SET status = 'ACTIVE', fail_streak = 0, last_error = NULL, 
                auto_skip_reason = NULL, cooldown_until = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now_str, group_id)
        )

    @staticmethod
    async def autoclean() -> int:
        """Skip (is_skipped = 1) any group with fail_streak >= 3 or specific broken statuses."""
        now_str = state.get_target_now().isoformat()
        # Query count before cleaning
        rows = await db.fetchall(
            """
            SELECT id FROM groups 
            WHERE is_skipped = 0 AND (fail_streak >= 3 OR status IN ('MUTED', 'NO_PERMISSION', 'INVALID'))
            """
        )
        if not rows:
            return 0
            
        for r in rows:
            await db.execute(
                """
                UPDATE groups 
                SET is_skipped = 1, auto_skip_reason = 'Autocleaned due to high failures / permission errors', updated_at = ? 
                WHERE id = ?
                """,
                (now_str, r["id"])
            )
        return len(rows)

    @staticmethod
    async def handle_delivery_error(group_id: int, exception: Exception):
        """Map Telethon/RPC exceptions to database status and logs."""
        now_str = state.get_target_now().isoformat()
        err_msg = str(exception)
        logger.warning(f"Handling delivery error for group ID {group_id}: {type(exception).__name__}: {err_msg}")
        
        status = "FAILED"
        cooldown_until = None
        auto_skip_reason = None
        
        if isinstance(exception, FloodWaitError):
            status = "FLOOD_WAIT"
            cooldown_time = state.get_target_now() + timedelta(seconds=exception.seconds)
            cooldown_until = cooldown_time.isoformat()
            auto_skip_reason = f"FloodWait for {exception.seconds}s"
            
        elif isinstance(exception, SlowModeWaitError):
            status = "FLOOD_WAIT"
            cooldown_time = state.get_target_now() + timedelta(seconds=exception.seconds)
            cooldown_until = cooldown_time.isoformat()
            auto_skip_reason = f"SlowMode wait for {exception.seconds}s"
            
        elif isinstance(exception, ChatWriteForbiddenError):
            status = "MUTED"
            auto_skip_reason = "Chat write forbidden (muted by admin/slowmode)"
            
        elif isinstance(exception, (UserBannedInChannelError, ChannelPrivateError, ChatAdminRequiredError)):
            status = "NO_PERMISSION"
            auto_skip_reason = f"No permission to post: {type(exception).__name__}"
            
        elif isinstance(exception, (UsernameInvalidError, UsernameNotOccupiedError)):
            status = "INVALID"
            auto_skip_reason = "Invalid username or entity does not exist"
            
        else:
            # General errors increment fail streak
            group = await db.fetchone("SELECT fail_streak FROM groups WHERE id = ?", (group_id,))
            current_streak = group["fail_streak"] if group else 0
            new_streak = current_streak + 1
            
            if new_streak >= 3:
                status = "FAILED"
                auto_skip_reason = f"Failed 3 times consecutively. Last: {err_msg}"
                await db.execute(
                    """
                    UPDATE groups 
                    SET status = ?, last_error = ?, last_send_status = 'failed', 
                        fail_streak = ?, auto_skip_reason = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, err_msg, new_streak, auto_skip_reason, now_str, group_id)
                )
            else:
                # Keep current status but log error & increment streak
                await db.execute(
                    """
                    UPDATE groups 
                    SET last_error = ?, last_send_status = 'failed', 
                        fail_streak = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (err_msg, new_streak, now_str, group_id)
                )
            return

        # For mapped status updates (FloodWait, No Permission, Muted, Invalid)
        await db.execute(
            """
            UPDATE groups 
            SET status = ?, last_error = ?, last_send_status = 'failed', 
                auto_skip_reason = ?, cooldown_until = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, err_msg, auto_skip_reason, cooldown_until, now_str, group_id)
        )

    @staticmethod
    async def verify_message_delivery(group_username_or_id: str, sent_msg_id: int, client=None) -> bool:
        """Fetch the last 5 messages from the group to check if our sent message is visible."""
        if client is None:
            client = telegram_client.get_client()
        try:
            target = group_username_or_id
            if target.replace("-", "").isdigit():
                target = int(target)
                
            messages = await client.get_messages(target, limit=5)
            for m in messages:
                if m.id == sent_msg_id:
                    return True
            return False
        except Exception as e:
            logger.warning(f"Verification of message visibility failed for {group_username_or_id}: {e}")
            return False

    @staticmethod
    async def check_group_entity(group_id: int, client=None) -> dict:
        """Query entity info from Telegram API and update status."""
        group = await GroupService.get_group(group_id)
        if not group:
            return {"status": "not_found", "error": "Group not found in database"}
            
        if client is None:
            client = telegram_client.get_client()
        peer_id = group.get("peer_id")
        target = peer_id if peer_id else group["username"]
        if not target:
            target = group["raw_input"]
            
        if isinstance(target, str) and target.replace("-", "").isdigit():
            target = int(target)
            
        now_str = state.get_target_now().isoformat()
        try:
            entity = await client.get_entity(target)
            title = getattr(entity, "title", "No Title")
            
            from telethon.utils import get_peer_id
            try:
                resolved_peer_id = get_peer_id(entity)
            except Exception:
                resolved_peer_id = getattr(entity, 'id', None)
                
            resolved_username = None
            if getattr(entity, 'username', None):
                resolved_username = "@" + entity.username.lower()
            else:
                resolved_username = str(resolved_peer_id)
            
            # Resolve default active state back and self-heal fields
            await db.execute(
                """
                UPDATE groups 
                SET peer_id = ?, username = ?, title = ?, status = 'ACTIVE', fail_streak = 0, last_error = NULL, 
                    auto_skip_reason = NULL, last_checked_at = ?, updated_at = ? 
                WHERE id = ?
                """,
                (resolved_peer_id, resolved_username, title, now_str, now_str, group_id)
            )
            return {"status": "success", "title": title}
        except Exception as e:
            await GroupService.handle_delivery_error(group_id, e)
            updated = await GroupService.get_group(group_id)
            return {"status": "failed", "error": str(e), "new_status": updated["status"]}

    @staticmethod
    async def check_all_groups_health() -> dict:
        """Inspect all non-skipped groups and resolve entities."""
        groups = await db.fetchall("SELECT * FROM groups WHERE is_skipped = 0")
        success_count = 0
        failed_count = 0
        
        for g in groups:
            res = await GroupService.check_group_entity(g["id"])
            if res["status"] == "success":
                success_count += 1
            else:
                failed_count += 1
                
        return {"total": len(groups), "success": success_count, "failed": failed_count}

    @staticmethod
    async def test_group_message(group_id: int, custom_msg: str = None, client=None) -> bool:
        """Send a test/manual message to a single group and update health status."""
        group = await GroupService.get_group(group_id)
        if not group:
            raise ValueError("Group not found")
            
        if client is None:
            client = telegram_client.get_client()
        peer_id = group.get("peer_id")
        target = peer_id if peer_id else group["username"]
        if not target:
            target = group["raw_input"]
            
        if isinstance(target, str) and target.replace("-", "").isdigit():
            target = int(target)
            
        # Get content
        if custom_msg:
            message_text = custom_msg
        else:
            templates = await db.fetchall("SELECT * FROM templates WHERE is_active = 1")
            if not templates:
                raise ValueError("No active templates found in database")
            import random
            message_text = random.choice(templates)["text"]
            
        now_str = state.get_target_now().isoformat()
        try:
            entity = None
            try:
                entity = await client.get_entity(target)
            except Exception:
                try:
                    entity = await resolve_target_entity(client, target)
                except Exception:
                    raw_target = group.get("raw_input")
                    if raw_target and raw_target != target:
                        entity = await resolve_target_entity(client, raw_target)
                    else:
                        raise
            
            if not entity:
                raise ValueError("Could not resolve target entity")
                
            sent_msg = await client.send_message(entity, message_text)
            
            # Post-delivery check: verify message is visible
            is_verified = await GroupService.verify_message_delivery(entity, sent_msg.id)
            send_status = "success" if is_verified else "unverified"
            
            await db.execute(
                """
                UPDATE groups 
                SET status = ?, last_send_status = ?, last_success_at = ?, 
                    fail_streak = 0, last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                ("ACTIVE" if is_verified else "UNVERIFIED", send_status, now_str, now_str, group_id)
            )
            return True
        except Exception as e:
            await GroupService.handle_delivery_error(group_id, e)
            return False

group_svc = GroupService()
