import sqlite3
import asyncio
import logging
from datetime import datetime
import config

logger = logging.getLogger("Database")

class AsyncDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    async def initialize(self):
        """Creates the required tables and populates initial values if empty."""
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Settings Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            # 2. Products Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT,
                    description TEXT,
                    inquiry_note TEXT,
                    sales_note TEXT,
                    requirement_note TEXT,
                    process_note TEXT,
                    warranty_note TEXT,
                    restriction_note TEXT,
                    is_active INTEGER DEFAULT 1,
                    autoorder_supported INTEGER DEFAULT 0,
                    autoorder_bot_username TEXT,
                    autoorder_bot_link TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            for col in ["sales_note", "requirement_note", "process_note", "warranty_note", "restriction_note"]:
                try:
                    cursor.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass
            
            # 3. Product Aliases Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    alias_text TEXT,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
                )
            """)
            
            # Product Variants / Packages Table (Legacy)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_variants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    note TEXT,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
                )
            """)
            try:
                cursor.execute("ALTER TABLE product_variants ADD COLUMN note TEXT")
            except sqlite3.OperationalError:
                pass

            # New Product Packages Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    package_name TEXT NOT NULL,
                    duration TEXT,
                    price INTEGER NOT NULL,
                    warranty_label TEXT,
                    warranty_detail TEXT,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
                )
            """)

            # Migrate legacy product_variants to product_packages
            cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='product_variants'")
            if cursor.fetchone()[0] > 0:
                cursor.execute("SELECT count(*) FROM product_packages")
                if cursor.fetchone()[0] == 0:
                    cursor.execute("SELECT count(*) FROM product_variants")
                    if cursor.fetchone()[0] > 0:
                        now_str = datetime.now().isoformat()
                        cursor.execute("""
                            INSERT INTO product_packages (product_id, package_name, price, notes, is_active, created_at, updated_at)
                            SELECT product_id, name, price, note, 1, ?, ? FROM product_variants
                        """, (now_str, now_str))
            
            # Product FAQs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_faqs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    question TEXT NOT NULL,
                    keywords TEXT,
                    answer TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
                )
            """)

            # 4. FAQ Templates Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS faq_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent TEXT UNIQUE,
                    keywords TEXT,
                    answer TEXT,
                    is_active INTEGER DEFAULT 1,
                    buttons TEXT
                )
            """)
            try:
                cursor.execute("ALTER TABLE faq_templates ADD COLUMN buttons TEXT")
            except sqlite3.OperationalError:
                pass
            
            # 5. Leads Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    question TEXT,
                    matched_product_id INTEGER,
                    matched_intent TEXT,
                    lead_score INTEGER DEFAULT 0,
                    created_at TEXT,
                    FOREIGN KEY(matched_product_id) REFERENCES products(id) ON DELETE SET NULL
                )
            """)
            try:
                cursor.execute("ALTER TABLE leads ADD COLUMN lead_score INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            # Conversation State Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_state (
                    telegram_user_id INTEGER PRIMARY KEY,
                    last_product_id INTEGER,
                    last_intent TEXT,
                    last_topic TEXT,
                    updated_at TEXT
                )
            """)

            # AI Usage Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER,
                    provider TEXT,
                    model TEXT,
                    status TEXT,
                    error_message TEXT,
                    created_at TEXT
                )
            """)

            # AI Cache Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_message TEXT,
                    context_hash TEXT,
                    reply_text TEXT,
                    intent TEXT,
                    product_id INTEGER,
                    created_at TEXT,
                    expires_at TEXT
                )
            """)
            
            # Seed default settings from config if not present
            default_settings = {
                "business_name": config.BUSINESS_NAME,
                "wa_link": config.WA_LINK,
                "channel_link": config.CHANNEL_LINK,
                "autoorder_bot_username": config.AUTOORDER_BOT_USERNAME,
                "autoorder_bot_link": config.AUTOORDER_BOT_LINK,
                "ai_enabled": "true",
                "gemini_model": "gemini-2.5-flash",
                "ai_temperature": "0.7",
                "ai_timeout_seconds": "8",
                "ai_max_calls_per_user_per_day": "30",
                "ai_daily_global_limit": "1000",
                "ai_style_strength": "medium",
                "bot_display_name": "Otan",
                "bot_role_desc": "Kamu adalah asisten front-desk CS di toko produk digital premium.",
                "bot_tone_style": "friendly, casual-professional, helpful, warm, tidak kaku, santai tapi sopan",
                "bot_emoji_level": "medium",
                "bot_humor_level": "medium",
                "bot_reply_length": "medium",
                "price_answer_mode": "exact_only",
                "out_of_scope_mode": "redirect"
            }
            for k, v in default_settings.items():
                cursor.execute("SELECT 1 FROM settings WHERE key = ?", (k,))
                if not cursor.fetchone():
                    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
            
            # Seed default FAQ templates if empty
            default_faqs = [
                (
                    "welcome",
                    "welcome",
                    "Halo kak! Selamat datang di toko kami 👋\n\nSaya adalah asisten front-desk toko kami. Saya siap membantu menjawab ketersediaan aplikasi premium, info cara beli, payment, dan garansi.\n\nSilakan gunakan menu tombol di bawah ini ya kak!"
                ),
                (
                    "help",
                    "help",
                    "💡 **Cara bertanya:**\n\nKakak bisa langsung mengetikkan nama aplikasi premium yang dicari. Contoh: `canva`, `netflix`, `youtube`, atau yang lainnya.\n\nAnda juga bisa menggunakan menu tombol bantuan utama."
                ),
                (
                    "cara_beli", 
                    "beli,cara beli,order,cara order,pemesanan", 
                    "Cara beli produk di toko kami gampang banget kak:\n\n1. Pilih aplikasi/produk yang ingin dibeli.\n2. Hubungi admin WhatsApp melalui tombol chat di bawah.\n3. Sebutkan produk yang mau di-order.\n4. Bayar sesuai instruksi pembayaran dari admin.\n5. Admin akan mengirimkan detail akses produk kakak."
                ),
                (
                    "payment", 
                    "bayar,payment,metode bayar,rekening,qris,bank,gopay,dana,ovo", 
                    "Kami menerima berbagai metode pembayaran kak, antara lain:\n- QRIS (E-Wallet: DANA, OVO, GoPay, LinkAja)\n- Transfer Bank (BCA, Mandiri, BNI, BRI)\n\nDetail nomor rekening/QRIS akan langsung diberikan oleh admin saat proses checkout di WhatsApp."
                ),
                (
                    "garansi", 
                    "garansi,klaim,complaint,komplain,warranty,mati,bermasalah,error", 
                    "Semua produk kami dilindungi oleh garansi resmi sesuai durasi paket kak.\n\nJika ada kendala (misal premium mati/error), jangan panik ya. Langsung kirim detail kendala & bukti order/email terdaftar ke WhatsApp admin agar segera dibantu proses perbaikan atau replacement."
                ),
                (
                    "fallback",
                    "fallback",
                    "Mohon maaf kak, Otan belum mengerti pertanyaan kakak.\n\nJika ada pertanyaan khusus atau butuh bantuan lebih lanjut, kakak bisa langsung tanya ke admin WhatsApp kami ya."
                )
            ]
            for intent, keywords, answer in default_faqs:
                cursor.execute("SELECT 1 FROM faq_templates WHERE intent = ?", (intent,))
                if not cursor.fetchone():
                    # Attempt to load custom settings if they exist to migrate them
                    final_answer = answer
                    final_buttons = None
                    if intent == "welcome":
                        cursor.execute("SELECT value FROM settings WHERE key = 'bot_welcome_msg'")
                        row = cursor.fetchone()
                        if row:
                            final_answer = row[0]
                        cursor.execute("SELECT value FROM settings WHERE key = 'bot_welcome_buttons'")
                        row_btn = cursor.fetchone()
                        if row_btn:
                            final_buttons = row_btn[0]
                        else:
                            final_buttons = (
                                "📁 Katalog Produk | catalog || 📝 Cara Beli | cara_beli\n"
                                "💳 Payment / Bayar | payment || 🛡️ Garansi & Klaim | garansi\n"
                                "💬 Chat Admin WA | wa_admin"
                            )
                    elif intent == "help":
                        cursor.execute("SELECT value FROM settings WHERE key = 'bot_help_msg'")
                        row = cursor.fetchone()
                        if row:
                            final_answer = row[0]
                        cursor.execute("SELECT value FROM settings WHERE key = 'bot_help_buttons'")
                        row_btn = cursor.fetchone()
                        if row_btn:
                            final_buttons = row_btn[0]
                    
                    cursor.execute(
                        "INSERT INTO faq_templates (intent, keywords, answer, is_active, buttons) VALUES (?, ?, ?, 1, ?)",
                        (intent, keywords, final_answer, final_buttons)
                    )
            
            conn.commit()
            logger.info("Database initialized successfully.")

    async def execute(self, query: str, params: tuple = ()) -> int:
        """Executes a modification query (INSERT, UPDATE, DELETE). Returns lastrowid."""
        return await asyncio.to_thread(self._execute_sync, query, params)

    def _execute_sync(self, query: str, params: tuple) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid

    async def fetchone(self, query: str, params: tuple = ()):
        """Fetches a single row. Returns a sqlite3.Row dict or None."""
        row = await asyncio.to_thread(self._fetchone_sync, query, params)
        return dict(row) if row else None

    def _fetchone_sync(self, query: str, params: tuple):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()

    async def fetchall(self, query: str, params: tuple = ()) -> list:
        """Fetches all matching rows. Returns a list of dicts."""
        rows = await asyncio.to_thread(self._fetchall_sync, query, params)
        return [dict(r) for r in rows]

    def _fetchall_sync(self, query: str, params: tuple):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()

db = AsyncDatabase(config.DATABASE_PATH)
