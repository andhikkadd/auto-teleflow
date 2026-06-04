import json
import logging
from datetime import datetime
from database import db
from services.settings_service import settings_svc
from services.product_service import product_svc
from services.faq_service import faq_svc
from services.lead_service import lead_svc
from services.ai_service import AIService
from services.intent_service import intent_svc
from services.reply_service import reply_svc
import config

logger = logging.getLogger("BotFlowService")

class BotFlowService:
    @staticmethod
    async def get_session_state(user_id: int) -> dict:
        """Loads the session state for a user."""
        row = await db.fetchone("SELECT * FROM conversation_state WHERE telegram_user_id = ?", (user_id,))
        if row:
            return dict(row)
        return {"telegram_user_id": user_id, "last_product_id": None, "last_intent": None, "last_topic": None}

    @staticmethod
    async def save_session_state(user_id: int, product_id: int = None, intent: str = None, topic: str = None):
        """Saves the session state for a user."""
        now_str = datetime.now().isoformat()
        await db.execute(
            """
            INSERT INTO conversation_state (telegram_user_id, last_product_id, last_intent, last_topic, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                last_product_id = excluded.last_product_id,
                last_intent = excluded.last_intent,
                last_topic = excluded.last_topic,
                updated_at = excluded.updated_at
            """,
            (user_id, product_id, intent, topic, now_str)
        )

    @staticmethod
    def is_follow_up(query: str) -> bool:
        """Determines if a query is likely a follow-up inquiry referencing the previous product."""
        follow_up_words = [
            "ada", "harga", "garansi", "paket", "berapa", "email", "kak", "ya", "cara", "order", 
            "beli", "payment", "bayar", "tanya", "itu", "ini", "ready", "ongkir", "durasi", "spek",
            "syarat", "akses", "cara beli", "cara order", "fitur", "akun", "pro", "premium"
        ]
        query_words = query.lower().split()
        return any(word in query_words for word in follow_up_words) or len(query_words) <= 3

    @staticmethod
    async def match_product(query: str, session: dict) -> tuple[dict, str]:
        """
        Tries to match a product based on direct names, aliases, fuzzy logic, or session history.
        Returns (matched_product_dict or None, match_method)
        """
        cleaned_query = query.strip().lower()
        if not cleaned_query:
            return None, "empty"

        # Load active products
        active_products = await product_svc.get_active_products()
        if not active_products:
            return None, "no_products"

        # 1. Substring/Direct Matches
        choices = {}
        for p in active_products:
            choices[p["name"].lower()] = p
            aliases = await product_svc.get_aliases_for_product(p["id"])
            for alias in aliases:
                choices[alias["alias_text"].lower()] = p

        direct_matches = []
        for term, product in choices.items():
            if term in cleaned_query:
                direct_matches.append((term, product))

        if direct_matches:
            direct_matches.sort(key=lambda x: len(x[0]), reverse=True)
            return direct_matches[0][1], "direct"

        # 2. Fuzzy Match via RapidFuzz (using intent_svc logic)
        match_res = await intent_svc.match_intent(query)
        if match_res["type"] == "product":
            return match_res["matched_object"], "fuzzy"

        # 3. Session Context Fallback
        if session.get("last_product_id") and BotFlowService.is_follow_up(query):
            last_prod = await product_svc.get_product_by_id(session["last_product_id"])
            if last_prod and last_prod["is_active"] == 1:
                return last_prod, "session"

        return None, "none"

    @staticmethod
    async def compile_db_context(product: dict = None) -> dict:
        """Compiles facts database context for the AI prompt engine."""
        biz_name = await settings_svc.get_setting("business_name", config.BUSINESS_NAME)
        wa_link = await settings_svc.get_setting("wa_link", config.WA_LINK)
        channel_link = await settings_svc.get_setting("channel_link", config.CHANNEL_LINK)
        autoorder_link = await settings_svc.get_setting("autoorder_bot_link", config.AUTOORDER_BOT_LINK)

        # Base structure
        context = {
            "store_settings": {
                "business_name": biz_name,
                "wa_link": wa_link,
                "channel_link": channel_link,
                "autoorder_bot_link": autoorder_link
            },
            "matched_product": None,
            "product_packages": [],
            "product_faqs": [],
            "general_faqs": []
        }

        # Matched product specific facts
        if product:
            context["matched_product"] = {
                "id": product["id"],
                "name": product["name"],
                "description": product["description"],
                "autoorder_supported": product["autoorder_supported"],
                "autoorder_bot_username": product["autoorder_bot_username"],
                "autoorder_bot_link": product["autoorder_bot_link"]
            }
            # Packages
            packages = await product_svc.get_packages_for_product(product["id"])
            context["product_packages"] = [
                {
                    "package_name": pkg["package_name"],
                    "price": pkg["price"],
                    "warranty_note": pkg.get("notes") or "",
                    "is_active": pkg["is_active"]
                }
                for pkg in packages if pkg["is_active"] == 1
            ]
            # Product FAQ
            prod_faqs = await product_svc.get_faqs_for_product(product["id"])
            context["product_faqs"] = [
                {
                    "question": f["question"],
                    "answer": f["answer"]
                }
                for f in prod_faqs if f["is_active"] == 1
            ]

        # General FAQs
        general_faqs = await faq_svc.get_all_faqs()
        context["general_faqs"] = [
            {
                "intent": f["intent"],
                "keywords": f["keywords"],
                "answer": f["answer"]
            }
            for f in general_faqs if f["is_active"] == 1
        ]

        return context

    @staticmethod
    def validate_ai_reply(reply_data: dict, db_context: dict) -> bool:
        """Validates that the AI reply is safe, factual, and doesn't invent terms."""
        reply_text = reply_data.get("reply_text", "")
        if not reply_text:
            return False

        # 1. Verify no invented prices
        # Extract numbers from text (e.g. 15000, 15.000, 15,000)
        import re
        numbers_in_reply = re.findall(r'\b\d+(?:[\.,]\d+)*\b', reply_text)
        
        # If numbers are present, verify they exist in product packages or FAQ
        if numbers_in_reply:
            valid_numbers = set()
            # Add package prices
            for pkg in db_context.get("product_packages", []):
                valid_numbers.add(str(pkg["price"]))
                # Add price divided by 1000 or formatted (e.g., 15)
                valid_numbers.add(str(pkg["price"] // 1000))
            
            # Check if any number in the reply text looks like an invented price (greater than 1000 and not matching any package price)
            for num_str in numbers_in_reply:
                cleaned_num = num_str.replace(".", "").replace(",", "")
                if cleaned_num.isdigit():
                    val = int(cleaned_num)
                    if val > 1000:
                        # It is a price value, let's verify it matches one of our packages
                        price_matched = False
                        for pkg in db_context.get("product_packages", []):
                            if val == pkg["price"]:
                                price_matched = True
                        if not price_matched:
                            # Hallucinated price!
                            logger.warning("AI validation failed: Reply contains hallucinated price '%s'", num_str)
                            return False

        # 2. Verify it does not validate payments or send credentials
        forbidden_keywords = [
            "pembayaran berhasil", "sudah lunas", "akun terkirim", "payment valid", "validated",
            "password anda", "email:", "password:"
        ]
        for kw in forbidden_keywords:
            if kw in reply_text.lower():
                logger.warning("AI validation failed: Reply contains forbidden keyword '%s'", kw)
                return False

        return True

    @staticmethod
    async def get_out_of_scope_reply() -> str:
        """Generates a varied natural Indonesian out-of-scope response."""
        import random
        replies = [
            "Wkwk kalau itu aku skip dulu ya kak 😭\nAku lebih jago bantu soal app premium, harga, cara beli, payment, sama garansi di sini.\n\nMau cek app apa?",
            "Haha kalau itu di luar yang aku handle kak.\nTapi kalau soal app premium, pricelist, cara order, atau garansi, aku gas bantuin. Kakak lagi cari app apa nih?",
            "Aduh kak, kalau itu Otan kurang paham 🙈\nOtan di sini fokusnya bantu kakak cek harga, spek, cara order, dan garansi app premium. Mau tanya-tanya app apa?"
        ]
        return random.choice(replies)

    @staticmethod
    async def get_error_fallback_reply() -> str:
        """Error fallback message directing to WhatsApp support."""
        return "Bentar kak, aku arahin ke admin aja ya biar infonya tetap aman dan nggak salah. Bisa langsung chat WA admin buat dicek."

    @staticmethod
    async def process_user_message(user_id: int, username: str, first_name: str, message_text: str) -> dict:
        """
        The main pipeline to route, context-compile, cache, query Gemini,
        validate, log, and return the final reply.
        """
        normalized_query = message_text.strip().lower()

        # 1. Get user session history
        session = await BotFlowService.get_session_state(user_id)

        # 2. Match product
        product, match_method = await BotFlowService.match_product(message_text, session)
        product_id = product["id"] if product else None

        # 3. Check if AI is enabled & usable
        enabled_str = await settings_svc.get_setting("ai_enabled", "") or os.getenv("AI_ENABLED", "true")
        ai_enabled = enabled_str.lower() in ("true", "1", "yes", "on")

        ai_key = await AIService.get_api_key()

        # 4. Process flow
        if ai_enabled and ai_key:
            # Prepare context
            db_context = await BotFlowService.compile_db_context(product)

            # Query AI
            ai_res = await AIService.generate_reply(user_id, normalized_query, message_text, db_context)

            # Validate AI response
            if ai_res.get("error"):
                # Fallback to rule-based because of API errors/limits
                logger.warning("AI Service returned error: %s. Using rule-based fallback.", ai_res["error"])
                reply_data = await BotFlowService.get_rule_based_reply(message_text, product)
            elif ai_res.get("intent") == "OUT_OF_SCOPE":
                reply_data = {
                    "text": await BotFlowService.get_out_of_scope_reply(),
                    "buttons": [{"text": "💬 Chat Admin WA", "url": await reply_svc.get_wa_link()}],
                    "intent": "OUT_OF_SCOPE",
                    "lead_score": 0
                }
            elif not BotFlowService.validate_ai_reply(ai_res, db_context):
                # Validation failed, use rule-based fallback
                logger.warning("AI output validation failed. Using rule-based fallback.")
                reply_data = await BotFlowService.get_rule_based_reply(message_text, product)
            else:
                # Compile buttons
                buttons = []
                wa_url = await reply_svc.get_wa_link()
                if ai_res.get("show_wa_button"):
                    buttons.append({"text": "💬 Chat Admin WA", "url": wa_url})
                if ai_res.get("show_autoorder_button") and product and product["autoorder_supported"] == 1:
                    ao_link = product["autoorder_bot_link"] or await settings_svc.get_setting("autoorder_bot_link", "")
                    if ao_link:
                        buttons.append({"text": "⚡ Bot Autoorder", "url": ao_link})
                
                reply_data = {
                    "text": ai_res["reply_text"],
                    "buttons": buttons,
                    "intent": ai_res["intent"],
                    "lead_score": ai_res.get("lead_score", 0)
                }

        else:
            # AI is disabled or API key missing, run rule-based
            logger.info("AI is disabled/missing key. Using rule-based engine.")
            reply_data = await BotFlowService.get_rule_based_reply(message_text, product)

        # 5. Log Lead
        await lead_svc.add_lead(
            telegram_user_id=user_id,
            username=username,
            first_name=first_name,
            question=message_text,
            matched_product_id=product_id,
            matched_intent=reply_data["intent"],
            lead_score=reply_data.get("lead_score", 0)
        )

        # 6. Save Session State
        await BotFlowService.save_session_state(
            user_id=user_id,
            product_id=product_id,
            intent=reply_data["intent"],
            topic=product["name"] if product else "general"
        )

        return reply_data

    @staticmethod
    async def get_rule_based_reply(message_text: str, product: dict = None) -> dict:
        """Rule-based matching fallback using intent_svc and reply_svc."""
        match_res = await intent_svc.match_intent(message_text)
        
        # Override matched product if already detected by smarter pipeline
        if product and match_res["type"] != "product":
            match_res = {
                "type": "product",
                "matched_id": product["id"],
                "matched_ref": product["name"],
                "matched_object": product,
                "confidence": 100.0
            }

        reply_data = await reply_svc.format_reply(match_res, message_text)
        
        # Determine lead score
        lead_score = 0
        if match_res["type"] == "product":
            lead_score = 70
        elif match_res["matched_ref"] in ["cara_beli", "payment"]:
            lead_score = 50

        return {
            "text": reply_data["text"],
            "buttons": reply_data["buttons"],
            "intent": match_res["matched_ref"],
            "lead_score": lead_score
        }
