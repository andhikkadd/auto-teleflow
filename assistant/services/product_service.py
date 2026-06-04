from datetime import datetime
from database import db

class ProductService:
    @staticmethod
    async def get_all_products() -> list:
        return await db.fetchall("SELECT * FROM products ORDER BY id DESC")

    @staticmethod
    async def get_active_products() -> list:
        return await db.fetchall("SELECT * FROM products WHERE is_active = 1 ORDER BY name ASC")

    @staticmethod
    async def get_product_by_id(product_id: int):
        return await db.fetchone("SELECT * FROM products WHERE id = ?", (product_id,))

    @staticmethod
    async def add_product(name: str, category: str, description: str, inquiry_note: str, is_active: int, autoorder_supported: int, autoorder_bot_username: str, autoorder_bot_link: str, sales_note: str = "", requirement_note: str = "", process_note: str = "", warranty_note: str = "", restriction_note: str = "") -> int:
        now_str = datetime.now().isoformat()
        return await db.execute(
            """
            INSERT INTO products (name, category, description, inquiry_note, sales_note, requirement_note, process_note, warranty_note, restriction_note, is_active, autoorder_supported, autoorder_bot_username, autoorder_bot_link, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, category, description, inquiry_note, sales_note, requirement_note, process_note, warranty_note, restriction_note, is_active, autoorder_supported, autoorder_bot_username, autoorder_bot_link, now_str, now_str)
        )

    @staticmethod
    async def update_product(product_id: int, name: str, category: str, description: str, inquiry_note: str, is_active: int, autoorder_supported: int, autoorder_bot_username: str, autoorder_bot_link: str, sales_note: str = "", requirement_note: str = "", process_note: str = "", warranty_note: str = "", restriction_note: str = ""):
        now_str = datetime.now().isoformat()
        await db.execute(
            """
            UPDATE products
            SET name = ?, category = ?, description = ?, inquiry_note = ?, sales_note = ?, requirement_note = ?, process_note = ?, warranty_note = ?, restriction_note = ?, is_active = ?, autoorder_supported = ?, autoorder_bot_username = ?, autoorder_bot_link = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, category, description, inquiry_note, sales_note, requirement_note, process_note, warranty_note, restriction_note, is_active, autoorder_supported, autoorder_bot_username, autoorder_bot_link, now_str, product_id)
        )

    @staticmethod
    async def delete_product(product_id: int):
        # Cascades to product_aliases if set up, but let's delete them manually to be safe
        await db.execute("DELETE FROM product_aliases WHERE product_id = ?", (product_id,))
        await db.execute("DELETE FROM product_variants WHERE product_id = ?", (product_id,))
        await db.execute("DELETE FROM product_packages WHERE product_id = ?", (product_id,))
        await db.execute("DELETE FROM product_faqs WHERE product_id = ?", (product_id,))
        await db.execute("DELETE FROM products WHERE id = ?", (product_id,))

    @staticmethod
    async def toggle_product_active(product_id: int):
        product = await ProductService.get_product_by_id(product_id)
        if product:
            new_status = 0 if product["is_active"] == 1 else 1
            now_str = datetime.now().isoformat()
            await db.execute(
                "UPDATE products SET is_active = ?, updated_at = ? WHERE id = ?",
                (new_status, now_str, product_id)
            )
            return new_status
        return None

    @staticmethod
    async def get_aliases_for_product(product_id: int) -> list:
        return await db.fetchall("SELECT * FROM product_aliases WHERE product_id = ? ORDER BY alias_text ASC", (product_id,))

    @staticmethod
    async def add_alias(product_id: int, alias_text: str) -> int:
        alias_cleaned = alias_text.strip().lower()
        # Check if exists
        existing = await db.fetchone(
            "SELECT id FROM product_aliases WHERE product_id = ? AND alias_text = ?", 
            (product_id, alias_cleaned)
        )
        if existing:
            return existing["id"]
        return await db.execute(
            "INSERT INTO product_aliases (product_id, alias_text) VALUES (?, ?)",
            (product_id, alias_cleaned)
        )

    @staticmethod
    async def delete_alias(alias_id: int):
        await db.execute("DELETE FROM product_aliases WHERE id = ?", (alias_id,))

    @staticmethod
    async def get_all_aliases() -> list:
        return await db.fetchall(
            """
            SELECT pa.*, p.name as product_name 
            FROM product_aliases pa
            JOIN products p ON pa.product_id = p.id
            ORDER BY p.name ASC, pa.alias_text ASC
            """
        )

    @staticmethod
    async def get_packages_for_product(product_id: int) -> list:
        return await db.fetchall("SELECT * FROM product_packages WHERE product_id = ? ORDER BY price ASC", (product_id,))

    @staticmethod
    async def get_variants_for_product(product_id: int) -> list:
        # Returns packages formatted for the legacy code (mapping package_name -> name, notes -> note)
        packages = await ProductService.get_packages_for_product(product_id)
        legacy_variants = []
        for p in packages:
            legacy_variants.append({
                "id": p["id"],
                "product_id": p["product_id"],
                "name": p["package_name"],
                "price": p["price"],
                "note": p["notes"],
                "duration": p.get("duration") or "",
                "warranty_label": p.get("warranty_label") or "",
                "warranty_detail": p.get("warranty_detail") or "",
                "is_active": p["is_active"]
            })
        return legacy_variants

    @staticmethod
    async def update_packages(product_id: int, packages_list: list):
        await db.execute("DELETE FROM product_packages WHERE product_id = ?", (product_id,))
        now_str = datetime.now().isoformat()
        for item in packages_list:
            if isinstance(item, dict):
                p_name = item.get("package_name") or item.get("name") or ""
                price = item.get("price", 0)
                notes = item.get("notes") or item.get("note") or ""
                duration = item.get("duration", "")
                w_label = item.get("warranty_label", "")
                w_detail = item.get("warranty_detail", "")
                is_active = item.get("is_active", 1)
            elif isinstance(item, (list, tuple)):
                if len(item) == 2:
                    p_name, price = item
                    notes, duration, w_label, w_detail, is_active = "", "", "", "", 1
                elif len(item) == 3:
                    p_name, price, notes = item
                    duration, w_label, w_detail, is_active = "", "", "", "", 1
                elif len(item) >= 7:
                    p_name, duration, price, w_label, w_detail, notes, is_active = item[:7]
                else:
                    continue
            else:
                continue

            if str(p_name).strip():
                try:
                    price_val = int(price)
                except (ValueError, TypeError):
                    price_val = 0
                await db.execute(
                    """
                    INSERT INTO product_packages (product_id, package_name, duration, price, warranty_label, warranty_detail, notes, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (product_id, str(p_name).strip(), str(duration).strip(), price_val, str(w_label).strip(), str(w_detail).strip(), str(notes).strip(), int(is_active), now_str, now_str)
                )

    @staticmethod
    async def update_variants(product_id: int, variants: list):
        # Keeps compatibility with legacy variant list updates
        await ProductService.update_packages(product_id, variants)

    # Product FAQs CRUD
    @staticmethod
    async def get_faqs_for_product(product_id: int) -> list:
        return await db.fetchall("SELECT * FROM product_faqs WHERE product_id = ? ORDER BY id DESC", (product_id,))

    @staticmethod
    async def get_all_product_faqs() -> list:
        return await db.fetchall(
            """
            SELECT pf.*, p.name as product_name
            FROM product_faqs pf
            JOIN products p ON pf.product_id = p.id
            ORDER BY p.name ASC, pf.id DESC
            """
        )

    @staticmethod
    async def add_product_faq(product_id: int, question: str, keywords: str, answer: str, is_active: int = 1):
        now_str = datetime.now().isoformat()
        return await db.execute(
            """
            INSERT INTO product_faqs (product_id, question, keywords, answer, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, question.strip(), keywords.strip(), answer.strip(), is_active, now_str, now_str)
        )

    @staticmethod
    async def update_product_faq(faq_id: int, question: str, keywords: str, answer: str, is_active: int):
        now_str = datetime.now().isoformat()
        await db.execute(
            """
            UPDATE product_faqs
            SET question = ?, keywords = ?, answer = ?, is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (question.strip(), keywords.strip(), answer.strip(), is_active, now_str, faq_id)
        )

    @staticmethod
    async def delete_product_faq(faq_id: int):
        await db.execute("DELETE FROM product_faqs WHERE id = ?", (faq_id,))

product_svc = ProductService()
