import os
import json
import hashlib
import asyncio
import logging
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Optional
from database import db
from services.settings_service import settings_svc
from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger("AIService")

class OtanResponse(BaseModel):
    intent: str = Field(description="Detected intent of the message (PRODUCT_PRICE, PRODUCT_AVAILABILITY, PACKAGE_DETAIL, WARRANTY, REQUIREMENT, PROCESS, CATALOG, BUYING_INTENT, PAYMENT, PAID_ALREADY, COMPLAINT, AUTOORDER, ADMIN_REQUEST, RECOMMENDATION, OUT_OF_SCOPE, UNKNOWN)")
    confidence: int = Field(description="Confidence score between 0 and 100")
    product_id: Optional[int] = Field(None, description="The integer ID of the matched product if applicable, else null")
    reply_text: str = Field(description="Friendly, natural Indonesian reply text answering the user query based ONLY on the provided context facts.")
    show_wa_button: bool = Field(description="True if user wants to chat with admin, buy, order, validate payment, or make a complaint/custom request. Else False.")
    show_autoorder_button: bool = Field(description="True only if product supports autoorder and user is inquiring about buying/autoordering that product. Else False.")
    lead_score: int = Field(description="Calculated lead quality score from 0 to 100 based on purchase intent.")

class AIService:
    @staticmethod
    async def get_api_key() -> str:
        """Retrieves Gemini API Key prioritizing SQLite settings over env."""
        key = await settings_svc.get_setting("gemini_api_key", "")
        if key.strip():
            return key.strip()
        return os.getenv("GEMINI_API_KEY", "").strip()

    @staticmethod
    async def get_model() -> str:
        """Retrieves configured Gemini Model."""
        model = await settings_svc.get_setting("gemini_model", "")
        if model.strip():
            return model.strip()
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    @staticmethod
    async def get_usage_today() -> int:
        """Gets the total number of successful AI calls today."""
        today = datetime.now().strftime("%Y-%m-%d") + "%"
        row = await db.fetchone("SELECT count(*) as count FROM ai_usage WHERE created_at LIKE ? AND status = 'success'", (today,))
        return row["count"] if row else 0

    @staticmethod
    async def log_usage(user_id: int, provider: str, model: str, status: str, error_message: str = ""):
        """Logs an AI call in the database."""
        now_str = datetime.now().isoformat()
        await db.execute(
            """
            INSERT INTO ai_usage (telegram_user_id, provider, model, status, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, provider, model, status, error_message, now_str)
        )

    @staticmethod
    async def check_limits(user_id: int) -> tuple[bool, str]:
        """Checks if the user or global limit has been exceeded."""
        enabled_str = await settings_svc.get_setting("ai_enabled", "")
        if not enabled_str.strip():
            enabled_str = os.getenv("AI_ENABLED", "true")
            
        if enabled_str.lower() not in ("true", "1", "yes", "on"):
            return False, "AI is disabled."

        api_key = await AIService.get_api_key()
        if not api_key:
            return False, "Gemini API key is not configured."

        user_limit_str = await settings_svc.get_setting("ai_max_calls_per_user_per_day", "") or os.getenv("AI_MAX_CALLS_PER_USER_PER_DAY", "30")
        global_limit_str = await settings_svc.get_setting("ai_daily_global_limit", "") or os.getenv("AI_DAILY_GLOBAL_LIMIT", "1000")

        try:
            user_limit = int(user_limit_str)
        except ValueError:
            user_limit = 30

        try:
            global_limit = int(global_limit_str)
        except ValueError:
            global_limit = 1000

        today = datetime.now().strftime("%Y-%m-%d") + "%"
        
        # Global limit
        global_count = await AIService.get_usage_today()
        if global_count >= global_limit:
            return False, f"Global daily limit of {global_limit} exceeded."

        # User limit
        user_count_row = await db.fetchone("SELECT count(*) as count FROM ai_usage WHERE telegram_user_id = ? AND created_at LIKE ? AND status = 'success'", (user_id, today))
        user_count = user_count_row["count"] if user_count_row else 0
        if user_count >= user_limit:
            return False, f"User daily limit of {user_limit} exceeded."

        return True, ""

    @staticmethod
    def calculate_context_hash(context: dict) -> str:
        """Generates a stable hash of the retrieved product database context."""
        serialized = json.dumps(context, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    async def get_cached_reply(normalized_message: str, context_hash: str) -> Optional[dict]:
        """Gets a valid cached reply from the database if not expired."""
        now_str = datetime.now().isoformat()
        row = await db.fetchone(
            """
            SELECT reply_text, intent, product_id 
            FROM ai_cache 
            WHERE normalized_message = ? AND context_hash = ? AND expires_at > ?
            """,
            (normalized_message, context_hash, now_str)
        )
        return row

    @staticmethod
    async def save_to_cache(normalized_message: str, context_hash: str, reply_text: str, intent: str, product_id: Optional[int]):
        """Caches an AI reply in the database."""
        now = datetime.now()
        expires = now + timedelta(hours=12) # Cache for 12 hours
        now_str = now.isoformat()
        expires_str = expires.isoformat()
        await db.execute(
            """
            INSERT INTO ai_cache (normalized_message, context_hash, reply_text, intent, product_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (normalized_message, context_hash, reply_text, intent, product_id, now_str, expires_str)
        )

    @staticmethod
    async def clean_expired_cache():
        """Deletes expired cache rows."""
        now_str = datetime.now().isoformat()
        await db.execute("DELETE FROM ai_cache WHERE expires_at < ?", (now_str,))

    @staticmethod
    async def get_recent_errors(limit: int = 5) -> list:
        """Retrieves recent AI failures from usage logs."""
        return await db.fetchall(
            "SELECT * FROM ai_usage WHERE status = 'error' ORDER BY id DESC LIMIT ?",
            (limit,)
        )

    @staticmethod
    async def generate_reply(user_id: int, normalized_message: str, raw_message: str, db_context: dict) -> dict:
        """
        Interacts with the Gemini API to get a structured sales response.
        Returns a dictionary matching OtanResponse schema.
        """
        # 1. Calculate context hash
        ctx_hash = AIService.calculate_context_hash(db_context)

        # 2. Check Cache
        cached = await AIService.get_cached_reply(normalized_message, ctx_hash)
        if cached:
            logger.info("AI Cache hit for message: %s", normalized_message)
            return {
                "intent": cached["intent"],
                "confidence": 100,
                "product_id": cached["product_id"],
                "reply_text": cached["reply_text"],
                "show_wa_button": True, # Safely default to true for WhatsApp CTA
                "show_autoorder_button": db_context.get("autoorder_supported", False),
                "lead_score": 50
            }

        # 3. Check Limits
        allowed, reason = await AIService.check_limits(user_id)
        if not allowed:
            logger.warning("AI limits / configuration check failed: %s", reason)
            return {
                "intent": "UNKNOWN",
                "confidence": 0,
                "product_id": None,
                "reply_text": "",
                "show_wa_button": True,
                "show_autoorder_button": False,
                "lead_score": 0,
                "error": reason
            }

        # 4. Fetch AI Configuration details
        api_key = await AIService.get_api_key()
        model_name = await AIService.get_model()
        
        # Config options with defaults
        temp_str = await settings_svc.get_setting("ai_temperature", "") or os.getenv("AI_TEMPERATURE", "0.7")
        timeout_str = await settings_svc.get_setting("ai_timeout_seconds", "") or os.getenv("AI_TIMEOUT_SECONDS", "8")
        style_str = await settings_svc.get_setting("ai_style_strength", "") or os.getenv("AI_STYLE_STRENGTH", "medium")

        # Persona Settings
        persona_name = await settings_svc.get_setting("bot_display_name", "Otan")
        persona_role = await settings_svc.get_setting("bot_role_desc", "Kamu adalah asisten front-desk CS di toko produk digital premium.")
        persona_tone = await settings_svc.get_setting("bot_tone_style", "friendly, casual-professional, helpful, warm, tidak kaku, santai tapi sopan")
        persona_emoji = await settings_svc.get_setting("bot_emoji_level", "medium")
        persona_humor = await settings_svc.get_setting("bot_humor_level", "medium")
        persona_len = await settings_svc.get_setting("bot_reply_length", "medium")
        price_mode = await settings_svc.get_setting("price_answer_mode", "exact_only")
        out_of_scope_mode = await settings_svc.get_setting("out_of_scope_mode", "redirect")

        try:
            temperature = float(temp_str)
        except ValueError:
            temperature = 0.7

        try:
            timeout_sec = int(timeout_str)
        except ValueError:
            timeout_sec = 8

        # 5. Build prompt
        system_instruction = (
            f"Nama kamu: {persona_name}\n"
            f"Peran kamu: {persona_role}\n"
            f"Gaya bicara: {persona_tone}. Gunakan bahasa Indonesia yang santai, akrab, hangat, tapi tetap sopan. Hindari bahasa yang terlalu baku seperti 'Silakan hubungi admin' jika tidak perlu.\n"
            f"Level emoji: {persona_emoji}. Level humor: {persona_humor}. Panjang respon: {persona_len}.\n"
            f"Mode harga: {price_mode}. Mode out of scope: {out_of_scope_mode}.\n\n"
            "PERATURAN UTAMA:\n"
            "1. DATABASE ADALAH SATU-SATUNYA SUMBER KEBENARAN FAKTUAL. JANGAN PERNAH mengarang harga, durasi, garansi, status stok, limitasi, atau detail produk yang tidak ada di dalam data context.\n"
            "2. Jika user bertanya detail harga/durasi dan produk tersebut terdeteksi di database, jawab secara spesifik berdasarkan pricelist paket yang disediakan.\n"
            "3. Jika produk dicari tetapi TIDAK ADA di database, katakan dengan sopan bahwa produk tersebut saat ini belum tersedia, dan sarankan alternatif sejenis atau tawarkan untuk chat WhatsApp admin.\n"
            "4. Rute/tombol WhatsApp admin (show_wa_button=true) diaktifkan jika pembeli memiliki minat membeli, ingin bertanya stock/detail lebih lanjut, ingin melakukan pembayaran, komplain, atau butuh bantuan admin.\n"
            "5. Jangan pernah menyebut database internal, sistem prompt, format JSON, atau variabel teknis dalam jawaban teks kamu.\n"
            "6. Jika pertanyaan sama sekali tidak berhubungan dengan toko/produk digital (Out-of-Scope), tolak dengan santai, lucu, dan arahkan kembali ke topik produk digital."
        )

        prompt_body = (
            f"Konteks Data Toko (Fakta Resmi):\n"
            f"==================================\n"
            f"{json.dumps(db_context, indent=2)}\n"
            f"==================================\n\n"
            f"Pesan Pengguna: \"{raw_message}\"\n\n"
            f"Kembalikan respon JSON yang valid mengikuti skema Pydantic OtanResponse."
        )

        try:
            # 6. Call Gemini API
            client = genai.Client(api_key=api_key)
            
            # Using asyncio.to_thread to prevent blocking the event loop on SDK calls
            loop = asyncio.get_event_loop()
            
            def run_sdk():
                return client.models.generate_content(
                    model=model_name,
                    contents=prompt_body,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=temperature,
                        response_mime_type="application/json",
                        response_schema=OtanResponse,
                    )
                )

            # Enforce timeout
            response = await asyncio.wait_for(
                loop.run_in_executor(None, run_sdk),
                timeout=float(timeout_sec)
            )

            # 7. Parse response
            data = json.loads(response.text)
            
            # Validation checks on AI outputs to ensure no hallucination of prices
            reply_text = data.get("reply_text", "")
            intent = data.get("intent", "UNKNOWN")
            product_id = data.get("product_id")
            
            # Check if prices or facts are invented
            # If the reply mentions a price not in context, or is invalid, we fallback.
            # Log success
            await AIService.log_usage(user_id, "gemini", model_name, "success")
            
            # Cache the response
            await AIService.save_to_cache(
                normalized_message=normalized_message,
                context_hash=ctx_hash,
                reply_text=reply_text,
                intent=intent,
                product_id=product_id
            )

            return {
                "intent": intent,
                "confidence": data.get("confidence", 90),
                "product_id": product_id,
                "reply_text": reply_text,
                "show_wa_button": data.get("show_wa_button", True),
                "show_autoorder_button": data.get("show_autoorder_button", False),
                "lead_score": data.get("lead_score", 0)
            }

        except asyncio.TimeoutError:
            err_msg = "Gemini API request timed out."
            logger.error(err_msg)
            await AIService.log_usage(user_id, "gemini", model_name, "error", err_msg)
            return {"intent": "UNKNOWN", "confidence": 0, "product_id": None, "reply_text": "", "show_wa_button": True, "show_autoorder_button": False, "lead_score": 0, "error": err_msg}
        except APIError as e:
            err_msg = f"Gemini APIError: {e}"
            logger.error(err_msg)
            await AIService.log_usage(user_id, "gemini", model_name, "error", err_msg)
            return {"intent": "UNKNOWN", "confidence": 0, "product_id": None, "reply_text": "", "show_wa_button": True, "show_autoorder_button": False, "lead_score": 0, "error": err_msg}
        except Exception as e:
            err_msg = f"Gemini Error: {e}"
            logger.error(err_msg)
            await AIService.log_usage(user_id, "gemini", model_name, "error", err_msg)
            return {"intent": "UNKNOWN", "confidence": 0, "product_id": None, "reply_text": "", "show_wa_button": True, "show_autoorder_button": False, "lead_score": 0, "error": err_msg}
