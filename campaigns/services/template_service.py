import logging
from datetime import datetime
from database import db

logger = logging.getLogger("TemplateService")

class TemplateService:
    @staticmethod
    async def get_all_templates() -> list:
        return await db.fetchall("SELECT * FROM templates ORDER BY id ASC")

    @staticmethod
    async def get_active_templates() -> list:
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
