import logging
from datetime import datetime
from database import db

logger = logging.getLogger("TemplateService")

class TemplateService:
    @staticmethod
    async def get_all_templates() -> list:
        return await db.fetchall("SELECT * FROM templates ORDER BY id ASC")

    @staticmethod
    async def get_active_templates(include_override: bool = True) -> list:
        if include_override:
            from services.settings_service import settings_svc
            override_active = await settings_svc.get_setting("override_template_active", "0")
            if override_active == "1":
                override_until_str = await settings_svc.get_setting("override_template_until", "")
                if override_until_str:
                    try:
                        override_until = datetime.fromisoformat(override_until_str)
                        if datetime.now() < override_until:
                            override_text = await settings_svc.get_setting("override_template_text", "")
                            if override_text.strip():
                                return [{
                                    "id": 0,
                                    "text": override_text.strip(),
                                    "is_active": 1,
                                    "created_at": override_until_str,
                                    "updated_at": override_until_str
                                }]
                    except Exception as e:
                        logger.warning(f"Error parsing override_template_until: {e}")
        return await db.fetchall("SELECT * FROM templates WHERE is_active = 1")

    @staticmethod
    async def add_template(text: str) -> int:
        if not text:
            raise ValueError("Template content cannot be empty.")
        stripped = text.strip()
        if not stripped:
            raise ValueError("Template content cannot be empty.")
        if len(stripped) > 4096:
            raise ValueError("Template content exceeds Telegram's 4096 character limit.")
            
        now_str = datetime.now().isoformat()
        template_id = await db.execute(
            "INSERT INTO templates (text, is_active, created_at, updated_at) VALUES (?, 1, ?, ?)",
            (stripped, now_str, now_str)
        )
        logger.info(f"Added template ID {template_id}")
        return template_id

    @staticmethod
    async def delete_template(template_id: int):
        await db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        logger.info(f"Deleted template ID {template_id}")

template_svc = TemplateService()
