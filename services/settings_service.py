import logging
from datetime import datetime
from database import db
from utils import state

logger = logging.getLogger("SettingsService")

class SettingsService:
    @staticmethod
    async def get_setting(key: str, default: str = None) -> str:
        row = await db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    @staticmethod
    async def set_setting(key: str, value: str):
        now_str = datetime.now().isoformat()
        # Use INSERT OR REPLACE since settings has 'key' as PRIMARY KEY
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, str(value), now_str)
        )

    @staticmethod
    async def get_all_settings() -> dict:
        rows = await db.fetchall("SELECT key, value FROM settings")
        settings_dict = {row["key"]: row["value"] for row in rows}
        return settings_dict

    @staticmethod
    async def update_all_settings(
        min_delay: int,
        max_delay: int,
        delay_between_groups: int,
        send_report: bool,
        report_target: str,
        run_wave_on_start: bool,
        control_group: str = "",
        ghost_auditing_enabled: bool = False,
        ghost_auditing_limit: int = 10,
        ghost_auditing_action: str = "skip"
    ):
        # Update SQLite values
        await SettingsService.set_setting("min_delay", str(min_delay))
        await SettingsService.set_setting("max_delay", str(max_delay))
        await SettingsService.set_setting("delay_between_groups", str(delay_between_groups))
        await SettingsService.set_setting("send_report", "1" if send_report else "0")
        await SettingsService.set_setting("report_target", report_target)
        await SettingsService.set_setting("run_wave_on_start", "1" if run_wave_on_start else "0")
        await SettingsService.set_setting("control_group", control_group.strip())
        await SettingsService.set_setting("ghost_auditing_enabled", "1" if ghost_auditing_enabled else "0")
        await SettingsService.set_setting("ghost_auditing_limit", str(ghost_auditing_limit))
        await SettingsService.set_setting("ghost_auditing_action", ghost_auditing_action)
        
        # Update global memory state
        state.min_delay = min_delay
        state.max_delay = max_delay
        
        logger.info("System settings updated in database and synchronized in-memory state.")

settings_svc = SettingsService()
