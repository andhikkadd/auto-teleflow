from database import db

class SettingsService:
    @staticmethod
    async def get_setting(key: str, default: str = "") -> str:
        row = await db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        if row:
            return row["value"]
        return default

    @staticmethod
    async def set_setting(key: str, value: str):
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )

    @staticmethod
    async def update_all_settings(
        business_name: str,
        wa_link: str,
        channel_link: str,
        autoorder_bot_username: str,
        autoorder_bot_link: str
    ):
        await SettingsService.set_setting("business_name", business_name)
        await SettingsService.set_setting("wa_link", wa_link)
        await SettingsService.set_setting("channel_link", channel_link)
        await SettingsService.set_setting("autoorder_bot_username", autoorder_bot_username)
        await SettingsService.set_setting("autoorder_bot_link", autoorder_bot_link)

settings_svc = SettingsService()
