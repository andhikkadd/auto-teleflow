import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database import db
from services.intent_service import intent_svc
from services.reply_service import reply_svc
from services.lead_service import lead_svc
from services.settings_service import settings_svc
from services.bot_flow_service import BotFlowService

logger = logging.getLogger("TelegramBot")

# Initialize Bot and Dispatcher
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

def _build_inline_keyboard(buttons_data: list) -> InlineKeyboardMarkup:
    """Helper to construct InlineKeyboardMarkup from standard list of dicts."""
    builder = InlineKeyboardBuilder()
    for btn in buttons_data:
        builder.button(text=btn["text"], url=btn["url"])
    builder.adjust(1)  # Vertical stack
    return builder.as_markup()

def _build_custom_keyboard(
    buttons_str: str,
    wa_url: str,
    channel_link: str = "",
    ao_link: str = ""
) -> InlineKeyboardMarkup:
    """Builds inline keyboard from custom text format."""
    rows = []
    if not buttons_str:
        return None
        
    for line in buttons_str.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        row_buttons = []
        # Buttons on the same row are separated by "||"
        for btn_part in line.split("||"):
            btn_part = btn_part.strip()
            if "|" in btn_part:
                text, target = btn_part.split("|", 1)
                text = text.strip()
                target = target.strip()
                
                # Resolve targets
                if target == "wa_admin":
                    if wa_url and wa_url != "#":
                        row_buttons.append(InlineKeyboardButton(text=text, url=wa_url))
                elif target == "wa_order":
                    if wa_url and wa_url != "#":
                        import urllib.parse
                        encoded_text = urllib.parse.quote("Halo admin, saya mau order")
                        url = f"{wa_url}&text={encoded_text}" if "?" in wa_url else f"{wa_url}?text={encoded_text}"
                        row_buttons.append(InlineKeyboardButton(text=text, url=url))
                elif target == "wa_claim":
                    if wa_url and wa_url != "#":
                        import urllib.parse
                        encoded_text = urllib.parse.quote("Halo admin, saya mau klaim garansi")
                        url = f"{wa_url}&text={encoded_text}" if "?" in wa_url else f"{wa_url}?text={encoded_text}"
                        row_buttons.append(InlineKeyboardButton(text=text, url=url))
                elif target == "autoorder":
                    if ao_link:
                        row_buttons.append(InlineKeyboardButton(text=text, url=ao_link))
                elif target == "channel":
                    if channel_link:
                        row_buttons.append(InlineKeyboardButton(text=text, url=channel_link))
                elif target.startswith("http://") or target.startswith("https://"):
                    row_buttons.append(InlineKeyboardButton(text=text, url=target))
                else:
                    # Callback data
                    callback_val = target
                    if target == "catalog":
                        callback_val = "start_katalog"
                    elif target == "cara_beli":
                        callback_val = "faq:cara_beli"
                    elif target == "payment":
                        callback_val = "faq:payment"
                    elif target == "garansi":
                        callback_val = "faq:garansi"
                    row_buttons.append(InlineKeyboardButton(text=text, callback_data=callback_val))
        if row_buttons:
            rows.append(row_buttons)
            
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # Log lead
    await lead_svc.add_lead(
        telegram_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        question="/start",
        matched_intent="start"
    )
    
    biz_name = await settings_svc.get_setting("business_name", config.BUSINESS_NAME)
    wa_url = await reply_svc.get_wa_link()
    channel_link = await settings_svc.get_setting("channel_link", "")
    ao_link = await settings_svc.get_setting("autoorder_bot_link", "")
    
    welcome_faq = await db.fetchone("SELECT answer, buttons, is_active FROM faq_templates WHERE intent = 'welcome'")
    
    if welcome_faq and welcome_faq.get("is_active") == 1:
        greeting_raw = welcome_faq["answer"]
        buttons_str = welcome_faq["buttons"]
    else:
        greeting_raw = (
            f"Halo kak! Selamat datang di **{biz_name}** 👋\n\n"
            f"Saya **Otan**, asisten front-desk toko kami. Otan siap membantu menjawab "
            f"ketersediaan aplikasi premium, info cara beli, payment, dan garansi.\n\n"
            f"Silakan gunakan menu tombol di bawah ini ya kak!"
        )
        buttons_str = (
            "📁 Katalog Produk | catalog || 📝 Cara Beli | cara_beli\n"
            "💳 Payment / Bayar | payment || 🛡️ Garansi & Klaim | garansi\n"
            "💬 Chat Admin WA | wa_admin"
        )
        
    try:
        greeting = greeting_raw.format(business_name=biz_name)
    except Exception:
        greeting = greeting_raw
        
    keyboard = _build_custom_keyboard(buttons_str, wa_url, channel_link, ao_link)
    
    await message.answer(
        text=greeting,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.message(Command("katalog"))
async def cmd_katalog(message: types.Message):
    # Log lead
    await lead_svc.add_lead(
        telegram_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        question="/katalog",
        matched_intent="katalog"
    )
    
    catalog_res = await reply_svc.get_catalog_reply()
    keyboard = _build_inline_keyboard(catalog_res["buttons"])
    
    await message.answer(
        text=catalog_res["text"],
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    default_help = (
        "💡 **Cara bertanya ke Otan:**\n\n"
        "Kakak bisa langsung mengetikkan nama aplikasi premium yang dicari. "
        "Contoh: `canva`, `netflix`, `youtube`, atau yang lainnya.\n\n"
        "Otan juga mengerti beberapa kata kunci berikut:\n"
        "• `cara beli` - info proses pemesanan\n"
        "• `payment` - info metode pembayaran\n"
        "• `garansi` - info garansi & klaim kendala\n\n"
        "Atau silakan ketik `/start` untuk memunculkan menu tombol bantuan utama."
    )
    
    wa_url = await reply_svc.get_wa_link()
    channel_link = await settings_svc.get_setting("channel_link", "")
    ao_link = await settings_svc.get_setting("autoorder_bot_link", "")
    
    help_faq = await db.fetchone("SELECT answer, buttons, is_active FROM faq_templates WHERE intent = 'help'")
    if help_faq and help_faq.get("is_active") == 1:
        help_text = help_faq["answer"]
        buttons_str = help_faq["buttons"]
    else:
        help_text = default_help
        buttons_str = ""
        
    keyboard = _build_custom_keyboard(buttons_str, wa_url, channel_link, ao_link)
    
    await message.answer(text=help_text, parse_mode="Markdown", reply_markup=keyboard)

# Handle Callback Queries from Start Menu
@dp.callback_query(F.data == "start_katalog")
async def cb_katalog(callback: types.CallbackQuery):
    catalog_res = await reply_svc.get_catalog_reply()
    keyboard = _build_inline_keyboard(catalog_res["buttons"])
    
    await callback.message.answer(
        text=catalog_res["text"],
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("faq:"))
async def cb_faq(callback: types.CallbackQuery):
    intent = callback.data.split(":")[1]
    match_result = {
        "type": "faq",
        "matched_id": None,
        "matched_ref": intent,
        "matched_object": await db.fetchone("SELECT * FROM faq_templates WHERE intent = ?", (intent,))
    }
    
    faq_res = await reply_svc.format_reply(match_result, "")
    keyboard = _build_inline_keyboard(faq_res["buttons"])
    
    await callback.message.answer(
        text=faq_res["text"],
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await callback.answer()

# Handle Free Text Queries
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(message: types.Message):
    query = message.text.strip()
    
    # Process the message via our AI/Rule-based sales flow pipeline
    reply_data = await BotFlowService.process_user_message(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        message_text=query
    )
    
    # Deliver response
    keyboard = _build_inline_keyboard(reply_data["buttons"])
    await message.answer(
        text=reply_data["text"],
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def start_bot():
    """Starts the Telegram bot long polling."""
    logger.info("Initializing Bot Services...")
    await db.initialize()
    logger.info("Starting Telegram Bot listener...")
    # Delete webhook to ensure clean long polling setup
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
