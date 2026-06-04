from database import db

class FaqService:
    @staticmethod
    async def get_all_faqs() -> list:
        return await db.fetchall("SELECT * FROM faq_templates ORDER BY intent ASC")

    @staticmethod
    async def get_faq_by_intent(intent: str):
        return await db.fetchone("SELECT * FROM faq_templates WHERE intent = ?", (intent,))

    @staticmethod
    async def update_faq(intent: str, answer: str, keywords: str = None, is_active: int = 1, buttons: str = ""):
        if keywords is not None:
            await db.execute(
                "UPDATE faq_templates SET answer = ?, keywords = ?, is_active = ?, buttons = ? WHERE intent = ?",
                (answer, keywords, is_active, buttons, intent)
            )
        else:
            await db.execute(
                "UPDATE faq_templates SET answer = ?, is_active = ?, buttons = ? WHERE intent = ?",
                (answer, is_active, buttons, intent)
            )

    @staticmethod
    async def get_active_faqs() -> list:
        return await db.fetchall("SELECT * FROM faq_templates WHERE is_active = 1")

faq_svc = FaqService()
