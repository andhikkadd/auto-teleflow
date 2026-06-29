import asyncio
import logging
import os
import random
from datetime import datetime
from telethon import events
from telethon.errors import RPCError

import config
from database import db
from utils import state, sanitize_logs
import server_status
import telegram_client

# Import Services Layer
from services.group_service import group_svc
from services.template_service import template_svc
from services.settings_service import settings_svc
from services.wave_service import wave_svc
from services.backup_service import backup_svc

logger = logging.getLogger("Commands")

def is_authorized(sender_id: int, sender_username: str) -> bool:
    """Check if the sender is authorized as the Master admin."""
    # 1. Prioritize MASTER_ID check if available
    if config.MASTER_ID is not None:
        return sender_id == config.MASTER_ID
    
    # 2. Check MASTER_USERNAME
    if config.MASTER_USERNAME:
        clean_master = config.MASTER_USERNAME.lower().lstrip("@")
        if sender_username:
            clean_sender = sender_username.lower().lstrip("@")
            return clean_sender == clean_master
                
    return False

async def register_handlers(clients: list = None):
    """Register command message event listener on all active Telethon clients."""
    if clients is None:
        clients = telegram_client.get_active_clients()

    async def command_router(event):
        sender = await event.get_sender()
        sender_id = event.sender_id
        sender_username = sender.username if sender else None
        
        # Prevent responding to self
        try:
            me = await event.client.get_me()
            if me and sender_id == me.id:
                return
        except Exception:
            me = None

        # Verify authorization
        authorized = is_authorized(sender_id, sender_username)
        
        # DB logging of command
        now_str = datetime.now().isoformat()
        status_str = "allowed" if authorized else "denied"
        await db.execute(
            "INSERT INTO command_logs (sender_id, sender_username, text, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (sender_id, sender_username, event.text, status_str, now_str)
        )
        
        if not authorized:
            logger.warning(f"Unauthorized command attempt by user {sender_id} (@{sender_username}): {event.text}")
            # Silently ignore to prevent disclosure of bot's active existence
            return

        # Restrict command execution to Private Chats (PM) or the configured Control Group Target
        from services.settings_service import settings_svc
        control_group_raw = await settings_svc.get_setting("control_group", "")
        
        is_allowed_chat = False
        if event.is_private:
            is_allowed_chat = True
        else:
            if control_group_raw:
                clean_control = control_group_raw.strip()
                chat_id_str = str(event.chat_id)
                
                # Check for direct ID match (e.g. -100123456789)
                if clean_control == chat_id_str:
                    is_allowed_chat = True
                else:
                    resolved_id = None
                    try:
                        if clean_control.replace("-", "").isdigit():
                            resolved_id = int(clean_control)
                        else:
                            from utils import resolve_target_entity
                            entity = await resolve_target_entity(event.client, clean_control)
                            if entity:
                                from telethon.utils import get_peer_id
                                resolved_id = get_peer_id(entity)
                    except Exception as resolve_err:
                        logger.warning(f"Could not resolve control group entity {clean_control}: {resolve_err}")

                    if resolved_id is not None:
                        try:
                            from telethon.utils import get_peer_id
                            event_peer_id = get_peer_id(await event.get_input_chat())
                            if event_peer_id == resolved_id:
                                is_allowed_chat = True
                        except Exception:
                            if event.chat_id == resolved_id or str(event.chat_id) == str(resolved_id):
                                is_allowed_chat = True
                    
                    if not is_allowed_chat:
                        try:
                            chat = await event.get_chat()
                            chat_username = getattr(chat, "username", None)
                            if chat_username and clean_control.lstrip("@").lower() == chat_username.lower():
                                is_allowed_chat = True
                        except Exception:
                            pass
            else:
                # If control_group is not set, allow commands anywhere for backward compatibility
                is_allowed_chat = True
                
        if not is_allowed_chat:
            # Silently ignore to avoid leakage or spam in public groups
            return

        # Parse command
        text = event.text
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg_str = parts[1].strip() if len(parts) > 1 else ""

        # Determine if this client is the primary client (first sorted by session filename)
        active_clients = sorted(
            telegram_client.get_active_clients(),
            key=lambda c: getattr(c.session, "filename", "")
        )
        is_primary = False
        if active_clients:
            try:
                if event.client.session.filename == active_clients[0].session.filename:
                    is_primary = True
            except Exception:
                pass

        # Utility commands that should only be handled once by the Master Bot
        single_response_cmds = (
            "!help", "!menu", "!server", "!backup", 
            "!addgroup", "!addgroups", "!groups", "!delgroup", 
            "!addtemplate", "!templates", "!deltemplate",
            "!setdelay", "!setgroupdelay", "!clean", "!autoclean",
            "!wave"
        )
        if not is_primary and cmd in single_response_cmds:
            return

        # Check for username targeting (e.g. !ping @bot_username)
        target_username = None
        if arg_str.startswith("@"):
            arg_parts = arg_str.split(maxsplit=1)
            target_username = arg_parts[0].lower().lstrip("@")
            arg_str = arg_parts[1].strip() if len(arg_parts) > 1 else ""
            
        if target_username and me:
            my_username = (me.username or "").lower()
            if target_username != my_username:
                # Command targeted at another bot, ignore
                return

        # Monkey-patch event.reply to automatically prepend the bot label
        if me:
            bot_label = f"🤖 **{me.first_name}**"
            if me.username:
                bot_label += f" (@{me.username})"
            
            original_reply = event.reply
            async def custom_reply(message, *args, **kwargs):
                custom_message = f"{bot_label}\n{message}"
                return await original_reply(custom_message, *args, **kwargs)
            event.reply = custom_reply

        logger.info(f"Admin command executed: {cmd} {arg_str}")
        
        try:
            if cmd in ("!help", "!menu"):
                await handle_help(event)
            elif cmd == "!ping":
                await event.reply("🏓 **Pong!** Bot promo aktif dan berjalan.")
            elif cmd == "!status":
                await handle_status(event)
            elif cmd == "!server":
                await handle_server(event)
            elif cmd == "!pause":
                await handle_pause(event)
            elif cmd == "!resume":
                await handle_resume(event)
            elif cmd == "!wave":
                await handle_wave(event)
            elif cmd == "!setdelay":
                await handle_setdelay(event, arg_str)
            elif cmd == "!setgroupdelay":
                await handle_setgroupdelay(event, arg_str)
            elif cmd == "!groups":
                await handle_groups(event)
            elif cmd == "!addgroup":
                await handle_addgroup(event, arg_str)
            elif cmd == "!delgroup":
                await handle_delgroup(event, arg_str)
            elif cmd == "!skip":
                await handle_skip(event, arg_str, skip=True)
            elif cmd == "!unskip":
                await handle_skip(event, arg_str, skip=False)
            elif cmd == "!templates":
                await handle_templates(event)
            elif cmd == "!addtemplate":
                await handle_addtemplate(event, arg_str)
            elif cmd == "!addtemplates":
                await handle_addtemplates(event, arg_str)
            elif cmd == "!addgroups":
                await handle_addgroups(event, arg_str)
            elif cmd == "!deltemplate":
                await handle_deltemplate(event, arg_str)
            elif cmd == "!delgroups":
                await handle_delgroups(event, arg_str)
            elif cmd == "!preview":
                await handle_preview(event)
            elif cmd == "!test":
                await handle_test(event, arg_str)
            elif cmd == "!backup":
                await handle_backup(event)
            elif cmd == "!logs":
                await handle_logs(event, arg_str)
            elif cmd == "!reload":
                await handle_reload(event)
            
            # New Group Health Commands
            elif cmd == "!checkgroups":
                await handle_checkgroups(event)
            elif cmd == "!checkgroup":
                await handle_checkgroup(event, arg_str)
            elif cmd == "!health":
                await handle_health(event)
            elif cmd == "!failedgroups":
                await handle_failedgroups(event)
            elif cmd == "!resetgroup":
                await handle_resetgroup(event, arg_str)
            elif cmd == "!autoclean":
                await handle_autoclean(event)
                
            else:
                await event.reply(f"❓ Command `{cmd}` tidak dikenal. Gunakan `!help` untuk daftar command.")
        except Exception as e:
            logger.exception(f"Error handling command {cmd}")
            sanitized_err = sanitize_logs(str(e))
            await event.reply(f"❌ Terjadi error saat mengeksekusi `{cmd}`: {type(e).__name__}: {sanitized_err}")

    for client in clients:
        try:
            client.remove_event_handler(command_router, events.NewMessage)
        except Exception:
            pass
        client.add_event_handler(command_router, events.NewMessage(pattern=r'^!'))

# Command Handler Implementations

async def handle_help(event):
    menu = (
        "🤖 **Telegram Userbot Promo - Menu Command**\n\n"
        "**Kontrol Bot:**\n"
        "• `!help` / `!menu` - Tampilkan daftar command ini.\n"
        "• `!ping` - Cek apakah bot merespon.\n"
        "• `!status` - Detail running state, delay, dan statistik.\n"
        "• `!server` - Performa server (CPU, RAM, Uptime).\n"
        "• `!pause` - Jeda scheduler wave otomatis.\n"
        "• `!resume` - Aktifkan kembali scheduler wave otomatis.\n"
        "• `!reload` - Muat ulang konfigurasi dari .env & database.\n\n"
        "**Manajemen Wave:**\n"
        "• `!wave` - Jalankan 1 wave promo manual sekarang.\n"
        "• `!setdelay <min> <max>` - Atur batas delay acak (menit).\n"
        "• `!setgroupdelay <min> <max>` - Atur batas delay acak antar grup (detik).\n"
        "• `!logs` - Ringkasan logs pengiriman wave terakhir.\n\n"
        "**Manajemen & Kesehatan Grup:**\n"
        "• `!groups` - Daftar grup target promo.\n"
        "• `!addgroup <username/link>` - Tambah grup target baru.\n"
        "• `!delgroup <id|username>` - Hapus grup target.\n"
        "• `!skip <id|username>` - Jeda pengiriman ke grup ini.\n"
        "• `!unskip <id|username>` - Aktifkan kembali pengiriman ke grup ini.\n"
        "• `!checkgroups` - Cek entitas & status semua grup (no promo).\n"
        "• `!checkgroup <id|username>` - Cek status satu grup.\n"
        "• `!health` - Ringkasan kesehatan semua grup.\n"
        "• `!failedgroups` - Tampilkan grup bermasalah & error terakhir.\n"
        "• `!resetgroup <id|username>` - Reset status grup ke ACTIVE.\n"
        "• `!autoclean` - Auto-skip grup rusak/error berturut-turut.\n\n"
        "**Manajemen Template:**\n"
        "• `!templates` - Daftar template pesan promo.\n"
        "• `!addtemplate <pesan>` - Tambah template pesan baru.\n"
        "• `!addtemplates <pesan1>||<pesan2>||...` - Tambah banyak template sekaligus, dipisahkan oleh `||`.\n"
        "• `!deltemplate <id>` - Hapus template pesan.\n"
        "• `!preview` - Tinjau template promo acak.\n"
        "• `!test <id|username> [pesan_kustom]` - Kirim test ke grup tertentu.\n\n"
        "**Backup & Keamanan:**\n"
        "• `!backup` - Buat backup terenkripsi (.gpg) dan kirim ke Telegram."
    )
    await event.reply(menu)

async def handle_status(event):
    active_grps = len(await db.fetchall("SELECT id FROM groups WHERE is_skipped = 0 AND status IN ('ACTIVE', 'UNVERIFIED')"))
    skipped_grps = len(await db.fetchall("SELECT id FROM groups WHERE is_skipped = 1 OR status = 'SKIPPED'"))
    active_temps = len(await template_svc.get_active_templates())
    
    state_str = "⏸️ **PAUSED**" if state.is_paused else "▶️ **RUNNING**"
    next_run = state.get_next_run_display()
    last_run = state.get_last_run_display()
    
    msg = (
        f"📊 **Status Framework Userbot**\n"
        f"• **Status**: {state_str}\n"
        f"• **Wave Terakhir**: `{last_run}`\n"
        f"• **Next Wave**: `{next_run}`\n"
        f"• **Rentang Delay**: `{state.min_delay} - {state.max_delay} menit`\n"
        f"• **Jumlah Grup**: `{active_grps} aktif / {skipped_grps} diskip`\n"
        f"• **Jumlah Template**: `{active_temps} aktif`"
    )
    await event.reply(msg)

async def handle_server(event):
    status_msg = server_status.format_server_status()
    await event.reply(status_msg)

async def handle_pause(event):
    await settings_svc.set_setting("paused", "1")
    state.is_paused = True
    await event.reply("⏸️ **Scheduler Wave Otomatis DIJEDA**.\nCommand admin tetap aktif.")

async def handle_resume(event):
    await settings_svc.set_setting("paused", "0")
    state.is_paused = False
    await event.reply("▶️ **Scheduler Wave Otomatis DIAKTIFKAN**.\nMenjadwalkan wave berikutnya...")

async def handle_wave(event):
    if state.active_wave_task is not None:
        await event.reply("⚠️ Wave promo sedang berjalan saat ini. Tunggu hingga selesai.")
        return
        
    await event.reply("🚀 **Triggering manual wave...** Memulai pengiriman promo.")
    asyncio.create_task(wave_svc.run_wave(f"Manual ({event.sender_id})"))

async def handle_setdelay(event, arg_str):
    parts = arg_str.split()
    if len(parts) < 2:
        await event.reply("⚠️ Format salah. Gunakan: `!setdelay <min_menit> <max_menit>`\nContoh: `!setdelay 60 180`")
        return
        
    try:
        val_min = int(parts[0])
        val_max = int(parts[1])
    except ValueError:
        await event.reply("⚠️ Nilai delay harus berupa angka integer.")
        return

    if val_min > val_max:
        val_min, val_max = val_max, val_min

    # Save to DB and State via settings service
    await settings_svc.set_setting("min_delay", str(val_min))
    await settings_svc.set_setting("max_delay", str(val_max))
    state.min_delay = val_min
    state.max_delay = val_max
    
    await event.reply(f"✅ **Delay berhasil diubah**:\n• Min: `{val_min} menit`\n• Max: `{val_max} menit`\nPerubahan diterapkan pada siklus berikutnya.")

async def handle_setgroupdelay(event, arg_str):
    parts = arg_str.split()
    if len(parts) < 2:
        current_min = await settings_svc.get_setting("delay_between_groups_min", None)
        current_max = await settings_svc.get_setting("delay_between_groups_max", None)
        
        if current_min is None or current_max is None:
            legacy_val = await settings_svc.get_setting("delay_between_groups", str(config.DELAY_BETWEEN_GROUPS_SECONDS))
            current_min = legacy_val
            current_max = legacy_val
            
        await event.reply(
            f"ℹ️ **Delay Antar Grup Saat Ini**:\n"
            f"• Min: `{current_min} detik`\n"
            f"• Max: `{current_max} detik`\n"
            f"Gunakan: `!setgroupdelay <min_detik> <max_detik>` untuk mengubah.\n"
            f"Contoh: `!setgroupdelay 15 45`"
        )
        return
        
    try:
        val_min = int(parts[0])
        val_max = int(parts[1])
    except ValueError:
        await event.reply("⚠️ Nilai delay harus berupa angka integer (detik).")
        return

    if val_min < 0 or val_max < 0:
        await event.reply("⚠️ Nilai delay tidak boleh kurang dari 0 detik.")
        return

    if val_min > val_max:
        val_min, val_max = val_max, val_min

    # Save to DB settings
    await settings_svc.set_setting("delay_between_groups_min", str(val_min))
    await settings_svc.set_setting("delay_between_groups_max", str(val_max))
    
    await event.reply(
        f"✅ **Delay antar grup berhasil diubah**:\n"
        f"• Min: `{val_min} detik`\n"
        f"• Max: `{val_max} detik`"
    )

async def handle_groups(event):
    groups = await group_svc.get_all_groups()
    if not groups:
        await event.reply("📁 **Daftar Grup Kosong**. Gunakan `!addgroup <username/link>` untuk menambah.")
        return
        
    lines = ["📁 **Daftar Target Grup:**"]
    for idx, g in enumerate(groups, 1):
        status_icon = "❌ SKIP" if (g["is_skipped"] == 1 or g["status"] == "SKIPPED") else f"✅ {g['status']}"
        title_str = g["title"] if g["title"] else "Unknown Title"
        uname_str = g["username"] if g["username"] else f"ID: {g['id']}"
        lines.append(f"{idx}. **{title_str}** ({uname_str}) - ID DB: `{g['id']}` - [{status_icon}]")
        
    await event.reply("\n".join(lines))

async def handle_addgroup(event, arg_str):
    if not arg_str:
        await event.reply("⚠️ Gunakan: `!addgroup <username_grup|link_grup>`")
        return
        
    await event.reply(f"🔍 Mencari entitas grup `{arg_str}`...")
    try:
        res = await group_svc.add_group(arg_str)
        if res["status"] == "exists":
            await event.reply(f"ℹ️ Grup `{arg_str}` sudah terdaftar di database (DB ID: `{res['group']['id']}`).")
        else:
            await event.reply(
                f"✅ **Grup Berhasil Ditambahkan**:\n"
                f"• **Judul**: {res['group']['title']}\n"
                f"• **Username**: {res['group']['username']}\n"
                f"• **DB ID**: `{res['group']['id']}`"
            )
    except Exception as e:
        sanitized_err = sanitize_logs(str(e))
        await event.reply(
            f"❌ **Gagal Menyelesaikan Grup**:\n"
            f"Tidak dapat memverifikasi grup `{arg_str}`.\n"
            f"Detail: {type(e).__name__}: {sanitized_err}"
        )

async def handle_addgroups(event, arg_str):
    """Bulk add groups separated by '||'.
    Example: !addgroups @group1||@group2||https://t.me/joinchat/xxxx
    """
    if not arg_str:
        await event.reply("⚠️ Gunakan: `!addgroups <ref1>||<ref2>||...`")
        return
    # normalize zero‑width characters
    clean_str = arg_str.replace('\u200b', '').replace('\u200c', '')
    refs = [r.strip() for r in clean_str.split('||') if r.strip()]
    if not refs:
        await event.reply("⚠️ Tidak ada grup yang valid untuk ditambahkan.")
        return
    added = []
    exists = []
    for ref in refs:
        try:
            res = await group_svc.add_group(ref)
            if res["status"] == "exists":
                exists.append(f"`{ref}` (ID: {res['group']['id']})")
            else:
                added.append(f"`{ref}` (ID: {res['group']['id']})")
        except Exception as e:
            logger.exception(f"Error adding group {ref}: {e}")
    msg_parts = []
    if added:
        msg_parts.append(f"✅ **{len(added)} grup berhasil ditambahkan:** {', '.join(added)}")
    if exists:
        msg_parts.append(f"ℹ️ **{len(exists)} grup sudah ada:** {', '.join(exists)}")
    if msg_parts:
        await event.reply('\n'.join(msg_parts))
    else:
        await event.reply("❌ Tidak ada grup yang berhasil ditambahkan.")

async def handle_delgroup(event, arg_str):
    if not arg_str:
        await event.reply("⚠️ Gunakan: `!delgroup <DB_ID|username>`")
        return
        
    target_group = await group_svc.get_group_by_ref(arg_str)
    if not target_group:
        await event.reply(f"⚠️ Grup `{arg_str}` tidak ditemukan di database.")
        return
        
    await group_svc.delete_group(target_group["id"])
    await event.reply(f"🗑️ Grup **{target_group['title']}** ({target_group['username']}) berhasil dihapus dari database.")

async def handle_skip(event, arg_str, skip=True):
    action_str = "skip" if skip else "unskip"
    if not arg_str:
        await event.reply(f"⚠️ Gunakan: `!{action_str} <DB_ID|username>`")
        return
        
    target_group = await group_svc.get_group_by_ref(arg_str)
    if not target_group:
        await event.reply(f"⚠️ Grup `{arg_str}` tidak ditemukan di database.")
        return
        
    await group_svc.set_skip(target_group["id"], skip)
    msg = f"⏸️ Grup **{target_group['title']}** diset untuk DISKIP." if skip else f"▶️ Grup **{target_group['title']}** DIAKTIFKAN kembali."
    await event.reply(msg)

async def handle_templates(event):
    templates = await template_svc.get_all_templates()
    if not templates:
        await event.reply("📝 **Daftar Template Kosong**.")
        return
        
    lines = ["📝 **Daftar Template Promo:**"]
    for t in templates:
        status_icon = "✅ AKTIF" if t["is_active"] else "❌ JEDA"
        snippet = t["text"][:60] + "..." if len(t["text"]) > 60 else t["text"]
        snippet_escaped = snippet.replace("\n", " ")
        lines.append(f"• ID `{t['id']}` - [{status_icon}] - `{snippet_escaped}`")
        
    await event.reply("\n".join(lines))

async def handle_addtemplate(event, arg_str):
    if not arg_str:
        await event.reply("⚠️ Gunakan: `!addtemplate <isi_pesan_promo>`")
        return
    # Jika pengguna secara tidak sengaja menggunakan !addtemplate dengan pemisah '||',
    # kita tetap dapat menambah banyak template.
    if "||" in arg_str:
        # normalize possible zero‑width characters
        clean_str = arg_str.replace('\u200b', '').replace('\u200c', '')
        templates = [t.strip() for t in clean_str.split('||') if t.strip()]
        logger.info(f"Parsed {len(templates)} templates in fallback addtemplate handler")
        if not templates:
            await event.reply("⚠️ Tidak ada template yang valid untuk ditambahkan.")
            return
        added_ids = []
        for tmpl in templates:
            try:
                t_id = await template_svc.add_template(tmpl)
                added_ids.append(str(t_id))
            except Exception as e:
                logger.exception(f"Error adding template: {e}")
        if added_ids:
            await event.reply(f"✅ **{len(added_ids)} template berhasil ditambahkan** (IDs: `{', '.join(added_ids)}`).")
        else:
            await event.reply("❌ Tidak ada template yang berhasil ditambahkan.")
        return
    # Penambahan tunggal standar
    t_id = await template_svc.add_template(arg_str)
    await event.reply(f"✅ **Template pesan berhasil ditambahkan** (ID: `{t_id}`).")
    
async def handle_addtemplates(event, arg_str):
    """Add multiple templates separated by '||'.
    Example: !addtemplates Pesan 1||Pesan 2||Pesan 3
    """
    if not arg_str:
        await event.reply("⚠️ Gunakan: `!addtemplates <pesan1>||<pesan2>||...`")
        return
    # normalize zero‑width chars that may appear in Telegram messages
    clean_str = arg_str.replace('\u200b', '').replace('\u200c', '')
    templates = [t.strip() for t in clean_str.split('||') if t.strip()]
    logger.info(f"Parsed {len(templates)} templates in addtemplates handler")
    if not templates:
        await event.reply("⚠️ Tidak ada template yang valid untuk ditambahkan.")
        return
    added_ids = []
    for tmpl in templates:
        try:
            t_id = await template_svc.add_template(tmpl)
            added_ids.append(str(t_id))
        except Exception as e:
            logger.exception(f"Error adding template: {e}")
    if added_ids:
        await event.reply(f"✅ **{len(added_ids)} template berhasil ditambahkan** (IDs: `{', '.join(added_ids)}`).")
    else:
        await event.reply("❌ Tidak ada template yang berhasil ditambahkan.")

async def handle_deltemplate(event, arg_str):
    if not arg_str or not arg_str.isdigit():
        await event.reply("⚠️ Gunakan: `!deltemplate <ID_template_DB>`")
        return
        
    t_id = int(arg_str)
    # Check minimum active template constraint
    active_temps = await template_svc.get_active_templates()
    if len(active_temps) <= 1:
        await event.reply("❌ **Gagal menghapus**: Minimal harus menyisakan 1 template aktif di sistem.")
        return
        
    await template_svc.delete_template(t_id)
    await event.reply(f"🗑️ Template ID `{t_id}` berhasil dihapus.")

async def handle_preview(event):
    templates = await template_svc.get_active_templates()
    if not templates:
        await event.reply("⚠️ Tidak ada template aktif untuk ditinjau.")
        return
        
    selected = random.choice(templates)
    await event.reply(
        f"📝 **Preview Template ID `{selected['id']}`**:\n"
        f"----------------------------------------\n"
        f"{selected['text']}"
    )

async def handle_test(event, arg_str):
    parts = arg_str.split(maxsplit=1)
    if not parts:
        await event.reply("⚠️ Gunakan: `!test <DB_ID|username> [pesan_kustom]`")
        return
        
    target_arg = parts[0]
    custom_msg = parts[1].strip() if len(parts) > 1 else None
    
    target_group = await group_svc.get_group_by_ref(target_arg)
    if not target_group:
        await event.reply(f"⚠️ Target `{target_arg}` tidak ditemukan di database.")
        return
        
    await event.reply(f"📤 Mengirim test message ke **{target_group['title']}**...")
    try:
        success = await group_svc.test_group_message(target_group["id"], custom_msg)
        if success:
            await event.reply(f"✅ Test message sukses terkirim ke **{target_group['title']}** (dan status terverifikasi).")
        else:
            await event.reply(f"❌ Test message terkirim tapi GAGAL verifikasi visibilitas ke **{target_group['title']}**.")
    except Exception as e:
        sanitized_err = sanitize_logs(str(e))
        await event.reply(f"❌ Test send GAGAL ke **{target_group['title']}**.\nDetail: {type(e).__name__}: {sanitized_err}")

async def handle_backup(event):
    await event.reply("📦 **Memulai proses backup data...**")
    try:
        backup_paths = await backup_svc.create_backup()
        client = event.client
        from utils import resolve_target_entity
        resolved_target = await resolve_target_entity(client, config.BACKUP_TARGET)
        
        for path in backup_paths:
            basename = os.path.basename(path)
            is_encrypted = path.endswith(".gpg")
            caption = (
                f"📦 **Backup File Userbot Promo**\n"
                f"• **File**: `{basename}`\n"
                f"• **Enkripsi**: {'🔒 AES256 GPG' if is_encrypted else '⚠️ ZIP Unencrypted'}\n"
                f"• **Waktu**: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                f"• Jangan berikan file backup ini ke siapapun!"
            )
            await client.send_file(resolved_target, path, caption=caption)
            # Clean local file
            backup_svc.clean_backup_file(path)
            
        await event.reply(f"✅ **Backup sukses terkirim** ({len(backup_paths)} berkas) ke target `{config.BACKUP_TARGET}`.")
    except Exception as e:
        sanitized_err = sanitize_logs(str(e))
        await event.reply(
            f"❌ **Backup GAGAL**\n"
            f"• **Error**: `{type(e).__name__}`\n"
            f"• **Pesan**: `{sanitized_err}`"
        )

async def handle_logs(event, arg_str):
    if arg_str and arg_str.isdigit():
        wave_id = int(arg_str)
        wave = await db.fetchone("SELECT * FROM wave_logs WHERE id = ?", (wave_id,))
        if not wave:
            await event.reply(f"⚠️ Wave ID `{wave_id}` tidak ditemukan.")
            return
    else:
        wave = await db.fetchone("SELECT * FROM wave_logs ORDER BY id DESC LIMIT 1")
        if not wave:
            await event.reply("⚠️ Belum ada logs wave tersimpan di database.")
            return
        
    items = await db.fetchall("SELECT * FROM wave_log_items WHERE wave_log_id = ? ORDER BY id ASC", (wave["id"],))
    
    duration = "N/A"
    if wave["finished_at"] and wave["started_at"]:
        start = datetime.fromisoformat(wave["started_at"])
        finish = datetime.fromisoformat(wave["finished_at"])
        duration = f"{(finish - start).total_seconds():.1f} detik"
        
    lines = [
        f"📝 **Log Wave ID `{wave['id']}`**",
        f"• **Dimulai**: `{wave['started_at']}`",
        f"• **Durasi**: `{duration}`",
        f"• **Hasil**: {wave['success_count']} Sukses / {wave['fail_count']} Gagal",
        f"• **Status**: `{wave['status'].upper()}`",
        f"\n📋 **Detail Pengiriman:**"
    ]
    
    for it in items:
        status_icon = "✅" if it["status"] == "success" else ("❓" if it["status"] == "unverified" else "❌")
        err_info = f" - Error: {it['error_message']}" if it["error_message"] else ""
        lines.append(f"- {status_icon} {it['group_title']}{err_info}")
        
    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n\n...(Dipotong karena terlalu panjang)"
    await event.reply(msg)

async def handle_reload(event):
    await event.reply("🔄 **Memuat ulang settings...**")
    from dotenv import load_dotenv
    from pathlib import Path
    
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
    
    try:
        paused_setting = await db.fetchone("SELECT value FROM settings WHERE key = 'paused'")
        if paused_setting:
            state.is_paused = (paused_setting["value"] == "1")
            
        min_setting = await db.fetchone("SELECT value FROM settings WHERE key = 'min_delay'")
        if min_setting:
            state.min_delay = int(min_setting["value"])
            
        max_setting = await db.fetchone("SELECT value FROM settings WHERE key = 'max_delay'")
        if max_setting:
            state.max_delay = int(max_setting["value"])
            
        await event.reply(
            f"✅ **Reload Sukses**:\n"
            f"• State: `{'Paused' if state.is_paused else 'Running'}`\n"
            f"• Delay: `{state.min_delay} - {state.max_delay} menit`"
        )
    except Exception as e:
        sanitized_err = sanitize_logs(str(e))
        await event.reply(f"❌ **Reload gagal**: {sanitized_err}")

# New Group Health Command Handlers

async def handle_checkgroups(event):
    await event.reply("🔍 **Memulai pemeriksaan kesehatan semua grup...**")
    res = await group_svc.check_all_groups_health()
    await event.reply(
        f"✅ **Pemeriksaan Grup Selesai**:\n"
        f"• Total Diperiksa: `{res['total']}`\n"
        f"• Sukses (Entity OK): `{res['success']}`\n"
        f"• Gagal (Error Mapped): `{res['failed']}`"
    )

async def handle_checkgroup(event, arg_str):
    if not arg_str:
        await event.reply("⚠️ Gunakan: `!checkgroup <DB_ID|username>`")
        return
        
    group = await group_svc.get_group_by_ref(arg_str)
    if not group:
        await event.reply(f"⚠️ Grup `{arg_str}` tidak ditemukan di database.")
        return
        
    await event.reply(f"🔍 Memeriksa grup **{group['title']}** ({group['username']})...")
    res = await group_svc.check_group_entity(group["id"])
    if res["status"] == "success":
        await event.reply(f"✅ **Koneksi Grup OK**: {res['title']} (ACTIVE)")
    else:
        sanitized_err = sanitize_logs(res['error'])
        await event.reply(f"❌ **Koneksi Grup GAGAL**: {sanitized_err} (Status baru: {res['new_status']})")

async def handle_health(event):
    active = len(await db.fetchall("SELECT id FROM groups WHERE is_skipped = 0 AND status = 'ACTIVE'"))
    skipped = len(await db.fetchall("SELECT id FROM groups WHERE is_skipped = 1 OR status = 'SKIPPED'"))
    flood = len(await db.fetchall("SELECT id FROM groups WHERE status = 'FLOOD_WAIT'"))
    muted = len(await db.fetchall("SELECT id FROM groups WHERE status = 'MUTED'"))
    no_perm = len(await db.fetchall("SELECT id FROM groups WHERE status = 'NO_PERMISSION'"))
    invalid = len(await db.fetchall("SELECT id FROM groups WHERE status = 'INVALID'"))
    failed = len(await db.fetchall("SELECT id FROM groups WHERE status = 'FAILED'"))
    unverified = len(await db.fetchall("SELECT id FROM groups WHERE status = 'UNVERIFIED'"))
    
    msg = (
        f"📊 **Kesehatan Grup & Channels**\n"
        f"• **ACTIVE / READY**: `{active}`\n"
        f"• **SKIPPED (Manual/Auto)**: `{skipped}`\n"
        f"• **FLOOD WAIT**: `{flood}`\n"
        f"• **MUTED (Forbidden)**: `{muted}`\n"
        f"• **NO PERMISSION**: `{no_perm}`\n"
        f"• **INVALID USERNAME**: `{invalid}`\n"
        f"• **FAILED (Streak 3+)**: `{failed}`\n"
        f"• **UNVERIFIED**: `{unverified}`"
    )
    await event.reply(msg)

async def handle_failedgroups(event):
    groups = await db.fetchall(
        """
        SELECT * FROM groups 
        WHERE status NOT IN ('ACTIVE', 'SKIPPED') OR fail_streak > 0 
        ORDER BY status ASC
        """
    )
    if not groups:
        await event.reply("✅ **Tidak ada grup bermasalah.** Semua target sehat.")
        return
        
    lines = ["⚠️ **Daftar Grup Bermasalah:**"]
    for idx, g in enumerate(groups, 1):
        err_info = f" - Error: {g['last_error']}" if g["last_error"] else ""
        lines.append(f"{idx}. **{g['title']}** ({g['username']}) - Status: `{g['status']}` - Fail: `{g['fail_streak']}/3`{err_info}")
        
    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n\n...(Dipotong karena terlalu panjang)"
    await event.reply(msg)

async def handle_resetgroup(event, arg_str):
    if not arg_str:
        await event.reply("⚠️ Gunakan: `!resetgroup <DB_ID|username>`")
        return
        
    group = await group_svc.get_group_by_ref(arg_str)
    if not group:
        await event.reply(f"⚠️ Grup `{arg_str}` tidak ditemukan di database.")
        return
        
    await group_svc.reset_group(group["id"])
    await event.reply(f"✅ Status grup **{group['title']}** telah direset ke ACTIVE (streak 0, error dibersihkan).")

async def handle_autoclean(event):
    await event.reply("🧼 **Menjalankan pembersihan otomatis grup bermasalah...**")
    cnt = await group_svc.autoclean()
    await event.reply(f"✅ **Auto-clean selesai**: `{cnt}` grup bermasalah dinonaktifkan (diset SKIP).")
