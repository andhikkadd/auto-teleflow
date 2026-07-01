import sys
sys.path.append(".")
import asyncio
from pathlib import Path
from telethon import TelegramClient
import config

async def test():
    session_path = Path("sessions") / "promo_userbot"
    client = TelegramClient(str(session_path), config.API_ID, config.API_HASH)
    print("Connecting client...")
    await client.connect()
    print("Client connected.")
    try:
        print("Getting entity...")
        entity = await client.get_entity("tuntungpedia")
        print("Success:", entity)
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(test())
