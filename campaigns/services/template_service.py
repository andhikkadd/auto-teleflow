import logging
from datetime import datetime
from database import db

logger = logging.getLogger("TemplateService")

class TemplateService:
    @staticmethod
    async def get_all_templates(is_override: int = 0) -> list:
        return await db.fetchall(
            "SELECT * FROM templates WHERE is_override = ? ORDER BY id ASC",
            (is_override,)
        )

    @staticmethod
    async def get_active_templates(include_override: bool = True) -> list:
        if include_override:
            from services.settings_service import settings_svc
            override_active = await settings_svc.get_setting("override_template_active", "0")
            if override_active == "1":
                override_until_str = await settings_svc.get_setting("override_template_until", "")
                if override_until_str:
                    try:
                        if override_until_str.endswith('Z') or '+' in override_until_str:
                            from datetime import timezone
                            iso_str = override_until_str[:-1] + "+00:00" if override_until_str.endswith('Z') else override_until_str
                            until_dt = datetime.fromisoformat(iso_str)
                            if until_dt.tzinfo is None:
                                until_dt = until_dt.replace(tzinfo=timezone.utc)
                            is_active = datetime.now(timezone.utc) < until_dt
                        else:
                            until_dt = datetime.fromisoformat(override_until_str)
                            is_active = datetime.now() < until_dt

                        if is_active:
                            # Return override templates strictly (can be empty if none created)
                            return await db.fetchall("SELECT * FROM templates WHERE is_override = 1 AND is_active = 1")
                        else:
                            # Expiration hit: auto-cleanup
                            await settings_svc.set_setting("override_template_active", "0")
                            await settings_svc.set_setting("override_template_until", "")
                            await db.execute("DELETE FROM templates WHERE is_override = 1")
                            logger.info("Override expired: automatically disabled override mode and deleted temporary templates.")
                    except Exception as e:
                        logger.warning(f"Error handling override expiration cleanup: {e}")
        return await db.fetchall("SELECT * FROM templates WHERE (is_override = 0 OR is_override IS NULL) AND is_active = 1")

    @staticmethod
    async def add_template(text: str, is_override: int = 0) -> int:
        if not text:
            raise ValueError("Template content cannot be empty.")
        stripped = text.strip()
        if not stripped:
            raise ValueError("Template content cannot be empty.")
        if len(stripped) > 4096:
            raise ValueError("Template content exceeds Telegram's 4096 character limit.")
            
        now_str = datetime.now().isoformat()
        template_id = await db.execute(
            "INSERT INTO templates (text, is_override, is_active, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, ?)",
            (stripped, is_override, now_str, now_str)
        )
        logger.info(f"Added template ID {template_id} (is_override={is_override})")
        return template_id

    @staticmethod
    async def delete_template(template_id: int):
        await db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        logger.info(f"Deleted template ID {template_id}")

template_svc = TemplateService()
