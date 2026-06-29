import logging
import re
import os
from datetime import datetime, timedelta
from typing import Optional
import asyncio

logger = logging.getLogger("Utils")

class GlobalState:
    def __init__(self):
        self.is_paused: bool = False
        self.active_wave_task: Optional[asyncio.Task] = None
        self.next_run_time: Optional[datetime] = None
        self.last_run_time: Optional[datetime] = None
        self.min_delay: int = 60
        self.max_delay: int = 180

    def get_next_run_in_seconds(self) -> float:
        if not self.next_run_time:
            return 0.0
        now = datetime.now()
        diff = (self.next_run_time - now).total_seconds()
        return max(0.0, diff)

    def get_next_run_display(self) -> str:
        if self.is_paused:
            return "Paused"
        if not self.next_run_time:
            return "Not scheduled"
        now = datetime.now()
        if now >= self.next_run_time:
            return "Imminent"
        diff = self.next_run_time - now
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}h {minutes:02d}m {seconds:02d}s"

    def get_last_run_display(self) -> str:
        if not self.last_run_time:
            return "Never"
        return self.last_run_time.strftime("%Y-%m-%d %H:%M:%S")

# Global singleton state
state = GlobalState()

def sanitize_logs(text: str) -> str:
    """Mask any sensitive details like passwords or hashes in log outputs."""
    if not text:
        return text
    
    # Retrieve secrets directly from environment variables to avoid circular imports
    api_hash = os.environ.get("API_HASH")
    backup_password = os.environ.get("BACKUP_PASSWORD")
    admin_password = os.environ.get("WEB_ADMIN_PASSWORD")
    session_secret = os.environ.get("WEB_SESSION_SECRET")
    
    # 1. Mask exact secrets
    if api_hash and len(api_hash) >= 8:
        text = text.replace(api_hash, '***MASKED_API_HASH***')
        
    if backup_password and len(backup_password) >= 3:
        text = text.replace(backup_password, '***MASKED_BACKUP_PASSWORD***')

    if admin_password and len(admin_password) >= 3:
        text = text.replace(admin_password, '***MASKED_ADMIN_PASSWORD***')

    if session_secret and len(session_secret) >= 3:
        text = text.replace(session_secret, '***MASKED_SESSION_SECRET***')

    # 2. Mask generic 32-character hexadecimal strings (standard format of API_HASH)
    text = re.sub(r'\b[a-fA-F0-9]{32}\b', '***MASKED_HEX_SECRET***', text)

    # 3. Mask numeric OTP patterns (usually 5 or 6 digits in Telegram alerts/logs)
    # Avoid matching generic short numbers like page sizes, but mask auth codes
    # We look for common labels indicating codes or standalone 5-6 digit numbers
    text = re.sub(r'(?i)\b(code|otp|verification|password|auth|login)[:\s-]*\d{5,6}\b', r'\1: ***MASKED_CODE***', text)
    # Mask standalone 5 or 6 digit codes that might be OTPs
    text = re.sub(r'\b\d{5,6}\b', '***MASKED_NUMERIC***', text)
    
    return text

def format_bytes(size: int) -> str:
    """Format bytes count to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    hours, mins = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {mins}m {secs}s"
    return f"{mins}m {secs}s"

async def resolve_target_entity(client, target):
    """
    Resolves a target (which can be a user ID, username, or an invite link)
    into a valid Telethon input peer or entity.
    """
    if not target:
        return None
        
    # If target is already an integer (e.g. peer ID)
    if isinstance(target, int):
        try:
            return await client.get_entity(target)
        except ValueError:
            logger.info(f"Entity ID {target} not found in cache. Fetching dialogs...")
            await client.get_dialogs()
            return await client.get_entity(target)
        
    target_str = str(target).strip()
    
    # If it is a digit or signed digit
    if target_str.replace("-", "").isdigit():
        target_int = int(target_str)
        try:
            return await client.get_entity(target_int)
        except ValueError:
            logger.info(f"Entity ID {target_int} not found in cache. Fetching dialogs...")
            await client.get_dialogs()
            return await client.get_entity(target_int)
        
    # Check if target is a Telegram link
    if "t.me/" in target_str or "telegram.me/" in target_str:
        # Extract the part after the last slash
        parts = target_str.split("/")
        # Find the last non-empty part
        clean_part = ""
        for p in reversed(parts):
            if p.strip():
                clean_part = p.strip()
                break
                
        # Check if it is an invite link (starts with '+' or was in 'joinchat/')
        is_invite = False
        if clean_part.startswith("+"):
            is_invite = True
            invite_hash = clean_part[1:]
        elif "joinchat" in target_str:
            is_invite = True
            invite_hash = clean_part
        else:
            # Standard username
            target_str = "@" + clean_part.lstrip("@")
            
        if is_invite:
            from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
            from telethon.errors import UserAlreadyParticipantError
            try:
                # Try to join the private channel/group first
                updates = await client(ImportChatInviteRequest(invite_hash))
                if hasattr(updates, "chats") and updates.chats:
                    return updates.chats[0]
            except UserAlreadyParticipantError:
                # If already joined, check invite info to get the chat/channel entity
                invite_info = await client(CheckChatInviteRequest(invite_hash))
                if hasattr(invite_info, "chat"):
                    return invite_info.chat
            except Exception as e:
                logger.error(f"Failed to join/resolve private chat invite hash {invite_hash}: {e}")
                raise e

    # Otherwise get normal entity (username or peer ID)
    try:
        return await client.get_entity(target_str)
    except ValueError:
        logger.info(f"Username {target_str} not found in cache. Fetching dialogs...")
        await client.get_dialogs()
        return await client.get_entity(target_str)
