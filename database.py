import sqlite3
import asyncio
import logging
from datetime import datetime
from pathlib import Path
import config

logger = logging.getLogger("Database")

class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DATABASE_PATH
        self.conn = None

    def connect(self):
        """Establish synchronous connection with check_same_thread=False and 30s timeout."""
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        # Use timeout=30.0 to handle database locked errors gracefully
        self.conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        logger.info(f"Connected to database at {self.db_path}")

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

    async def execute(self, sql: str, params: tuple = ()) -> int:
        """Run non-query SQL command in an executor to avoid blocking the event loop."""
        def _exec():
            try:
                cursor = self.conn.cursor()
                cursor.execute(sql, params)
                self.conn.commit()
                return cursor.lastrowid
            except sqlite3.Error as e:
                logger.error(f"Database execute error: {e} | SQL: {sql} | Params: {params}")
                raise
        return await asyncio.to_thread(_exec)

    async def fetchall(self, sql: str, params: tuple = ()) -> list:
        """Fetch all query records in an executor."""
        def _exec():
            try:
                cursor = self.conn.cursor()
                cursor.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
            except sqlite3.Error as e:
                logger.error(f"Database fetchall error: {e} | SQL: {sql}")
                raise
        return await asyncio.to_thread(_exec)

    async def fetchone(self, sql: str, params: tuple = ()) -> dict:
        """Fetch a single query record in an executor."""
        def _exec():
            try:
                cursor = self.conn.cursor()
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
            except sqlite3.Error as e:
                logger.error(f"Database fetchone error: {e} | SQL: {sql}")
                raise
        return await asyncio.to_thread(_exec)

    async def initialize_schema(self):
        """Create tables if they do not exist and initialize default values."""
        # 1. settings table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        """)

        # 2. groups table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                title TEXT,
                raw_input TEXT,
                is_skipped INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ACTIVE',
                last_send_status TEXT,
                last_error TEXT,
                last_checked_at TEXT,
                last_success_at TEXT,
                fail_streak INTEGER DEFAULT 0,
                auto_skip_reason TEXT,
                cooldown_until TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # 3. templates table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # 4. wave_logs table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS wave_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                status TEXT,
                success_count INTEGER,
                fail_count INTEGER
            )
        """)

        # 5. wave_log_items table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS wave_log_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wave_log_id INTEGER,
                group_id INTEGER,
                group_title TEXT,
                status TEXT,
                error_message TEXT,
                message_id INTEGER,
                FOREIGN KEY(wave_log_id) REFERENCES wave_logs(id)
            )
        """)

        # 6. command_logs table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS command_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                sender_username TEXT,
                text TEXT,
                status TEXT,
                created_at TEXT
            )
        """)

        # 7. session_proxies table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS session_proxies (
                session_name TEXT PRIMARY KEY,
                proxy_url TEXT,
                updated_at TEXT
            )
        """)

        # 8. auto_responder_logs table
        await self.execute("""
            CREATE TABLE IF NOT EXISTS auto_responder_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER,
                user_id INTEGER,
                replied_at TEXT
            )
        """)

        # Dynamic migrations check: check if the columns are in groups table
        columns_to_add = {
            "status": "TEXT DEFAULT 'ACTIVE'",
            "last_send_status": "TEXT",
            "last_error": "TEXT",
            "last_checked_at": "TEXT",
            "last_success_at": "TEXT",
            "fail_streak": "INTEGER DEFAULT 0",
            "auto_skip_reason": "TEXT",
            "cooldown_until": "TEXT"
        }

        info_rows = await self.fetchall("PRAGMA table_info(groups)")
        existing_columns = {row["name"] for row in info_rows}

        for col_name, col_def in columns_to_add.items():
            if col_name not in existing_columns:
                logger.info(f"Migrating database: Adding column '{col_name}' to 'groups' table...")
                try:
                    await self.execute(f"ALTER TABLE groups ADD COLUMN {col_name} {col_def}")
                except Exception as ex:
                    logger.warning(f"Failed to add column {col_name}: {ex}")

        # Dynamic migrations check: check if the columns are in templates table
        template_columns_to_add = {
            "is_override": "INTEGER DEFAULT 0",
            "override_until": "TEXT"
        }

        tpl_info_rows = await self.fetchall("PRAGMA table_info(templates)")
        existing_tpl_columns = {row["name"] for row in tpl_info_rows}

        for col_name, col_def in template_columns_to_add.items():
            if col_name not in existing_tpl_columns:
                logger.info(f"Migrating database: Adding column '{col_name}' to 'templates' table...")
                try:
                    await self.execute(f"ALTER TABLE templates ADD COLUMN {col_name} {col_def}")
                except Exception as ex:
                    logger.warning(f"Failed to add column {col_name} to templates: {ex}")

        # Dynamic migrations check: check if the columns are in session_proxies table
        proxies_columns_to_add = {
            "is_active": "INTEGER DEFAULT 1"
        }

        try:
            proxies_info_rows = await self.fetchall("PRAGMA table_info(session_proxies)")
            existing_proxies_columns = {row["name"] for row in proxies_info_rows}

            for col_name, col_def in proxies_columns_to_add.items():
                if col_name not in existing_proxies_columns:
                    logger.info(f"Migrating database: Adding column '{col_name}' to 'session_proxies' table...")
                    await self.execute(f"ALTER TABLE session_proxies ADD COLUMN {col_name} {col_def}")
        except Exception as ex:
            logger.warning(f"Failed to check/add columns to session_proxies: {ex}")

        # Insert default settings if they do not exist
        now_str = datetime.now().isoformat()
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("paused", "0", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("min_delay", str(config.DEFAULT_MIN_DELAY_MINUTES), now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("max_delay", str(config.DEFAULT_MAX_DELAY_MINUTES), now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("delay_between_groups", str(config.DELAY_BETWEEN_GROUPS_SECONDS), now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("send_report", "1" if config.SEND_REPORT else "0", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("report_target", str(config.BACKUP_TARGET), now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("run_wave_on_start", "1" if config.RUN_WAVE_ON_START else "0", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("ghost_auditing_enabled", "0", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("ghost_auditing_limit", "10", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("ghost_auditing_action", "skip", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("auto_responder_enabled", "0", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("auto_responder_text", "Halo! Untuk info pricelist lengkap, daftar kontak, dan cara pemesanan silakan langsung kunjungi Channel Resmi kami di @tuntungpedia.", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("auto_responder_cooldown", "24", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("auto_responder_keywords", "", now_str)
        )
        await self.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("timezone_offset", "7", now_str)
        )

        # Verify if there is at least one default template, insert one if empty
        templates = await self.fetchall("SELECT * FROM templates")
        if not templates:
            await self.execute(
                "INSERT INTO templates (text, is_active, created_at, updated_at) VALUES (?, 1, ?, ?)",
                ("Halo! Ini adalah template promo default. Silakan ganti dengan promo Anda.", now_str, now_str)
            )

        # Deduplicate groups by lowercase username if any exist
        try:
            duplicates = await self.fetchall(
                """
                SELECT id, username FROM groups 
                WHERE LOWER(username) IN (
                    SELECT LOWER(username) FROM groups 
                    GROUP BY LOWER(username) 
                    HAVING COUNT(*) > 1
                )
                ORDER BY LOWER(username) ASC, id ASC
                """
            )
            if duplicates:
                seen = set()
                to_delete = []
                for row in duplicates:
                    lower_uname = row["username"].lower()
                    if lower_uname in seen:
                        to_delete.append(row["id"])
                    else:
                        seen.add(lower_uname)
                
                if to_delete:
                    logger.info(f"Database Initialization: Cleaning up {len(to_delete)} duplicate group entries...")
                    placeholders = ",".join("?" for _ in to_delete)
                    await self.execute(f"DELETE FROM groups WHERE id IN ({placeholders})", tuple(to_delete))
        except Exception as dedup_err:
            logger.error(f"Error deduplicating groups in database startup: {dedup_err}")

        logger.info("Database schema initialized and default settings verified.")

# Instantiated single instance of database
db = Database()
db.connect()
# Note: Caller must run await db.initialize_schema() during startup
