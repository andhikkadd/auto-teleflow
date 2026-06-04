from datetime import datetime
from database import db

class LeadService:
    @staticmethod
    async def add_lead(telegram_user_id: int, username: str, first_name: str, question: str, matched_product_id: int = None, matched_intent: str = None, lead_score: int = 0) -> int:
        now_str = datetime.now().isoformat()
        return await db.execute(
            """
            INSERT INTO leads (telegram_user_id, username, first_name, question, matched_product_id, matched_intent, lead_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (telegram_user_id, username, first_name, question, matched_product_id, matched_intent, lead_score, now_str)
        )

    @staticmethod
    async def get_recent_leads(limit: int = 50) -> list:
        return await db.fetchall(
            """
            SELECT l.*, p.name as product_name
            FROM leads l
            LEFT JOIN products p ON l.matched_product_id = p.id
            ORDER BY l.id DESC
            LIMIT ?
            """,
            (limit,)
        )

    @staticmethod
    async def get_stats() -> dict:
        total_leads = await db.fetchone("SELECT COUNT(*) as count FROM leads")
        unique_users = await db.fetchone("SELECT COUNT(DISTINCT telegram_user_id) as count FROM leads")
        total_products = await db.fetchone("SELECT COUNT(*) as count FROM products")
        active_products = await db.fetchone("SELECT COUNT(*) as count FROM products WHERE is_active = 1")
        
        return {
            "total_leads": total_leads["count"] if total_leads else 0,
            "unique_users": unique_users["count"] if unique_users else 0,
            "total_products": total_products["count"] if total_products else 0,
            "active_products": active_products["count"] if active_products else 0
        }

    @staticmethod
    async def get_daily_usage_stats(days_limit: int = 7) -> dict:
        from datetime import datetime, timedelta
        rows = await db.fetchall(
            """
            SELECT date(created_at) as lead_date, COUNT(*) as lead_count 
            FROM leads 
            WHERE created_at >= date('now', ?)
            GROUP BY date(created_at)
            """,
            (f"-{days_limit} days",)
        )
        counts_by_date = {row["lead_date"]: row["lead_count"] for row in rows}
        
        chart_labels = []
        chart_data = []
        for i in range(days_limit - 1, -1, -1):
            day = datetime.now() - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            label = day.strftime("%d %b")
            chart_labels.append(label)
            chart_data.append(counts_by_date.get(day_str, 0))
            
        return {
            "labels": chart_labels,
            "data": chart_data
        }

    @staticmethod
    async def get_intent_breakdown() -> dict:
        prod_matches = await db.fetchone("SELECT COUNT(*) as count FROM leads WHERE matched_product_id IS NOT NULL")
        faq_matches = await db.fetchone(
            "SELECT COUNT(*) as count FROM leads WHERE matched_intent IS NOT NULL AND matched_intent != 'fallback' AND matched_product_id IS NULL"
        )
        fallback_matches = await db.fetchone(
            "SELECT COUNT(*) as count FROM leads WHERE matched_intent = 'fallback' AND matched_product_id IS NULL"
        )
        
        return {
            "Product Inquiries": prod_matches["count"] if prod_matches else 0,
            "FAQ Auto-Replies": faq_matches["count"] if faq_matches else 0,
            "Unresolved (Fallback)": fallback_matches["count"] if fallback_matches else 0
        }

lead_svc = LeadService()
