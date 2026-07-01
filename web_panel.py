import logging
import asyncio
import hmac
import secrets
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, Depends, status, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path

import config
from database import db
from utils import state, format_duration
from server_status import get_server_stats
from services.group_service import group_svc, clean_username_input
from services.template_service import template_svc
from services.settings_service import settings_svc
from services.wave_service import wave_svc
from services.backup_service import backup_svc
import telegram_client

logger = logging.getLogger("WebPanel")

# Initialize FastAPI App
app = FastAPI(title="Userbot Control Panel", docs_url=None, redoc_url=None)


def inject_csrf(request: Request):
    return {"csrf_token": request.session.get("csrf_token", "")}

# Setup Templates and Static files
templates = Jinja2Templates(
    directory="templates",
    context_processors=[inject_csrf]
)
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory stores for security features
failed_login_attempts = {}
action_cooldowns = {
    "manual_wave": datetime.min,
    "backup_run": datetime.min,
    "autoclean": datetime.min
}

def get_client_ip(request: Request) -> str:
    """Retrieve the client IP addressing proxy header trust configurations."""
    if config.WEB_TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def check_login_rate_limit(ip: str) -> bool:
    """Keep failed attempts from the last 10 minutes and restrict to max 5."""
    now = datetime.now()
    attempts = failed_login_attempts.get(ip, [])
    attempts = [t for t in attempts if (now - t).total_seconds() < 600]
    failed_login_attempts[ip] = attempts
    return len(attempts) < 5

def register_failed_login(ip: str):
    """Log failed login attempt timestamp."""
    now = datetime.now()
    attempts = failed_login_attempts.get(ip, [])
    attempts.append(now)
    failed_login_attempts[ip] = attempts

def check_action_cooldown(action_name: str, cooldown_seconds: int = 30) -> Optional[int]:
    """Ensure sensitive POST actions cannot be flooded. Returns cooldown seconds remaining."""
    now = datetime.now()
    last_run = action_cooldowns.get(action_name, datetime.min)
    elapsed = (now - last_run).total_seconds()
    if elapsed < cooldown_seconds:
        return int(cooldown_seconds - elapsed)
    action_cooldowns[action_name] = now
    return None

# Combined Middleware: auth protection and CSRF protection
@app.middleware("http")
async def csrf_and_auth_middleware(request: Request, call_next):
    # Auto-login if authenticated via Portal Gateway
    if request.headers.get("x-portal-authenticated") == "true":
        request.session["logged_in"] = True

    # Ensure session contains a CSRF token
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_hex(32)

    path = request.url.path
    is_public = path in ("/login", "/", "/favicon.ico") or path.startswith("/static")

    # 1. Route access control
    if not is_public and not request.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=303)

    # 2. CSRF Token Verification for POST requests
    if request.method == "POST":
        # Consuming the stream directly in middleware will exhaust it.
        # We read it once, then mock request._receive to allow subsequent reads.
        body = await request.body()
        
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
            
        request._receive = receive
        
        form_data = await request.form()
        token = form_data.get("csrf_token")
        session_token = request.session.get("csrf_token")

        if not token or not session_token or not hmac.compare_digest(str(token), str(session_token)):
            logger.warning(f"CSRF validation failure for client {get_client_ip(request)} on endpoint {path}")
            request.session["flash_danger"] = "Security validation failed. Please try again."
            referer = request.headers.get("referer", "/dashboard")
            if not request.session.get("logged_in"):
                referer = "/login"
            return RedirectResponse(url=referer, status_code=303)

    return await call_next(request)

# Add Session Middleware (Must be registered after csrf_and_auth_middleware so it wraps it)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.WEB_SESSION_SECRET,
    session_cookie="userbot_session",
    max_age=3600 * 24 # 1 day session
)

def get_flash_context(request: Request) -> dict:
    """Retrieve flash messages from the session and delete them."""
    success = request.session.pop("flash_success", None)
    danger = request.session.pop("flash_danger", None)
    return {"flash_success": success, "flash_danger": danger}

# Routes
@app.get("/")
async def root(request: Request):
    if request.session.get("logged_in"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)

@app.get("/login")
async def get_login(request: Request):
    if request.session.get("logged_in"):
        return RedirectResponse(url="/dashboard", status_code=303)
    context = {"request": request, "is_logged_in": False, **get_flash_context(request)}
    return templates.TemplateResponse(request, "login.html", context)

@app.post("/login")
async def post_login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = get_client_ip(request)
    if not check_login_rate_limit(ip):
        request.session["flash_danger"] = "Too many failed login attempts. Please try again in 10 minutes."
        return RedirectResponse(url="/login", status_code=303)

    # hmac.compare_digest prevents timing attacks
    valid_username = hmac.compare_digest(username.strip(), config.WEB_ADMIN_USERNAME)
    valid_password = hmac.compare_digest(password.strip(), config.WEB_ADMIN_PASSWORD)

    if valid_username and valid_password:
        failed_login_attempts[ip] = [] # Reset failed count on success
        request.session["logged_in"] = True
        request.session["flash_success"] = "Welcome back, Administrator!"
        return RedirectResponse(url="/dashboard", status_code=303)
        
    register_failed_login(ip)
    request.session["flash_danger"] = "Invalid admin credentials. Please try again."
    return RedirectResponse(url="/login", status_code=303)

@app.post("/logout")
async def post_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

@app.get("/dashboard")
async def get_dashboard(request: Request):
    # 1. Fetch server utilization stats
    server_stats = get_server_stats()
    
    # 2. Get group counts
    total = len(await group_svc.get_all_groups())
    
    active = len(await db.fetchall("SELECT id FROM groups WHERE is_skipped = 0 AND status IN ('ACTIVE', 'UNVERIFIED')"))
    skipped = len(await db.fetchall("SELECT id FROM groups WHERE is_skipped = 1 OR status = 'SKIPPED'"))
    failed = len(await db.fetchall("SELECT id FROM groups WHERE status = 'FAILED'"))
    flood = len(await db.fetchall("SELECT id FROM groups WHERE status = 'FLOOD_WAIT'"))
    muted = len(await db.fetchall("SELECT id FROM groups WHERE status = 'MUTED'"))
    unverified = len(await db.fetchall("SELECT id FROM groups WHERE status = 'UNVERIFIED'"))
    
    # 3. Get templates count
    templates_list = await template_svc.get_active_templates()
    
    # 4. Format scheduler timers
    last_run_str = "Never"
    if state.last_run_time:
        last_run_str = state.last_run_time.strftime("%Y-%m-%d %H:%M:%S")
        
    next_run_str = "Calculating..."
    if state.next_run_time:
        next_run_str = state.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
        
    # Get active delays
    min_del = await settings_svc.get_setting("min_delay", str(config.DEFAULT_MIN_DELAY_MINUTES))
    max_del = await settings_svc.get_setting("max_delay", str(config.DEFAULT_MAX_DELAY_MINUTES))
    delay_between = await settings_svc.get_setting("delay_between_groups", str(config.DELAY_BETWEEN_GROUPS_SECONDS))
    
    context = {
        "request": request,
        "is_logged_in": True,
        "active_page": "dashboard",
        "is_paused": state.is_paused,
        "is_wave_running": state.active_wave_task is not None,
        "last_wave_time": last_run_str,
        "next_wave_time": next_run_str,
        "total_groups": total,
        "active_groups": active,
        "skipped_groups": skipped,
        "failed_groups": failed,
        "flood_groups": flood,
        "muted_groups": muted,
        "unverified_groups": unverified,
        "total_templates": len(templates_list),
        "cpu_pct": server_stats["cpu_percent"],
        "ram_used": f"{(server_stats['ram_used'] / (1024**3)):.2f} GB",
        "ram_total": f"{(server_stats['ram_total'] / (1024**3)):.2f} GB",
        "ram_pct": server_stats["ram_percent"],
        "server_uptime": format_duration(server_stats["system_uptime"]),
        "bot_uptime": format_duration(server_stats["bot_uptime"]),
        "min_delay": min_del,
        "max_delay": max_del,
        "delay_between": delay_between,
        "is_gpg": backup_svc.is_gpg_available(),
        **get_flash_context(request)
    }
    return templates.TemplateResponse(request, "dashboard.html", context)

@app.post("/actions/pause")
async def action_pause(request: Request):
    await settings_svc.set_setting("paused", "1")
    state.is_paused = True
    request.session["flash_success"] = "Bot scheduler paused successfully."
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/actions/resume")
async def action_resume(request: Request):
    await settings_svc.set_setting("paused", "0")
    state.is_paused = False
    request.session["flash_success"] = "Bot scheduler resumed successfully."
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/actions/wave")
async def action_wave(request: Request):
    remaining = check_action_cooldown("manual_wave", cooldown_seconds=30)
    if remaining is not None:
        request.session["flash_danger"] = f"Manual wave is on cooldown. Please wait {remaining}s."
        return RedirectResponse(url="/dashboard", status_code=303)

    if state.active_wave_task is not None:
        request.session["flash_danger"] = "A promotional wave is already running."
    else:
        asyncio.create_task(wave_svc.run_wave("Web Dashboard"))
        request.session["flash_success"] = "Manual promo wave triggered in background."
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/groups")
async def get_groups(request: Request):
    groups_list = await group_svc.get_all_groups()
    context = {
        "request": request,
        "is_logged_in": True,
        "active_page": "groups",
        "groups": groups_list,
        **get_flash_context(request)
    }
    return templates.TemplateResponse(request, "groups.html", context)

@app.post("/groups/add")
async def post_add_group(request: Request, raw_input: str = Form(...)):
    try:
        res = await group_svc.add_group(raw_input)
        if res["status"] == "exists":
            request.session["flash_danger"] = f"Group '{raw_input}' already exists in target database."
        else:
            request.session["flash_success"] = f"Successfully resolved and added group: {res['group']['title']}."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to resolve or add group: {e}"
        
    return RedirectResponse(url="/groups", status_code=303)

@app.post("/groups/bulk-action")
async def post_groups_bulk_action(
    request: Request,
    action: str = Form(...),
    ids: str = Form(...)
):
    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
        if not id_list:
            request.session["flash_danger"] = "No groups selected for bulk action."
            return RedirectResponse(url="/groups", status_code=303)

        if action == "skip":
            for group_id in id_list:
                await group_svc.set_skip(group_id, True)
            request.session["flash_success"] = f"Successfully skipped {len(id_list)} selected groups."
        elif action == "unskip":
            for group_id in id_list:
                await group_svc.set_skip(group_id, False)
            request.session["flash_success"] = f"Successfully unskipped {len(id_list)} selected groups."
        elif action == "delete":
            for group_id in id_list:
                await group_svc.delete_group(group_id)
            request.session["flash_success"] = f"Successfully deleted {len(id_list)} selected groups."
        else:
            request.session["flash_danger"] = f"Unknown bulk action: {action}"
    except Exception as e:
        request.session["flash_danger"] = f"Failed to execute bulk action: {e}"

    return RedirectResponse(url="/groups", status_code=303)

@app.post("/groups/{id}/skip")
async def post_skip_group(request: Request, id: int):
    group = await group_svc.get_group(id)
    if not group:
        request.session["flash_danger"] = f"Group with DB ID {id} not found."
        return RedirectResponse(url="/groups", status_code=303)
        
    await group_svc.set_skip(id, True)
    request.session["flash_success"] = f"Group ID {id} manual skip enabled."
    return RedirectResponse(url="/groups", status_code=303)

@app.post("/groups/{id}/unskip")
async def post_unskip_group(request: Request, id: int):
    group = await group_svc.get_group(id)
    if not group:
        request.session["flash_danger"] = f"Group with DB ID {id} not found."
        return RedirectResponse(url="/groups", status_code=303)

    await group_svc.set_skip(id, False)
    request.session["flash_success"] = f"Group ID {id} manual skip disabled."
    return RedirectResponse(url="/groups", status_code=303)

@app.post("/groups/{id}/reset")
async def post_reset_group(request: Request, id: int, redirect: Optional[str] = None):
    group = await group_svc.get_group(id)
    if not group:
        request.session["flash_danger"] = f"Group with DB ID {id} not found."
        dest = "/health" if redirect == "health" else "/groups"
        return RedirectResponse(url=dest, status_code=303)

    await group_svc.reset_group(id)
    request.session["flash_success"] = f"Group ID {id} health attributes successfully reset."
    if redirect == "health":
        return RedirectResponse(url="/health", status_code=303)
    return RedirectResponse(url="/groups", status_code=303)

@app.post("/groups/{id}/delete")
async def post_delete_group(request: Request, id: int):
    group = await group_svc.get_group(id)
    if not group:
        request.session["flash_danger"] = f"Group with DB ID {id} not found."
        return RedirectResponse(url="/groups", status_code=303)

    await group_svc.delete_group(id)
    request.session["flash_success"] = f"Group ID {id} successfully deleted."
    return RedirectResponse(url="/groups", status_code=303)

@app.post("/groups/{id}/test")
async def post_test_group(request: Request, id: int, custom_msg: Optional[str] = Form(None)):
    group = await group_svc.get_group(id)
    if not group:
        request.session["flash_danger"] = f"Group with DB ID {id} not found."
        return RedirectResponse(url="/groups", status_code=303)

    try:
        success = await group_svc.test_group_message(id, custom_msg)
        if success:
            request.session["flash_success"] = f"Test message delivered successfully to group ID {id}."
        else:
            request.session["flash_danger"] = f"Test message failed delivery to group ID {id} (health status updated)."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to execute test message send: {e}"
        
    return RedirectResponse(url="/groups", status_code=303)

@app.get("/groups/search-telegram")
async def search_telegram_groups(q: str = ""):
    if not q or not q.strip():
        return JSONResponse({"status": "success", "results": []})
        
    client = telegram_client.get_client()
    if not client or not client.is_connected():
        return JSONResponse({"status": "error", "message": "Telegram client is not active/connected."}, status_code=400)
        
    from telethon.tl.functions.contacts import SearchRequest
    try:
        result = await client(SearchRequest(q=q.strip(), limit=50))
        discovered = []
        for chat in result.chats:
            is_group = False
            # Check if this chat object is a public group
            if hasattr(chat, 'megagroup') and chat.megagroup:
                is_group = True
            elif hasattr(chat, 'broadcast') and not chat.broadcast:
                is_group = True
                
            # Keep only public groups with usernames
            if is_group and getattr(chat, 'username', None):
                discovered.append({
                    "title": chat.title,
                    "username": f"@{chat.username}"
                })
        return JSONResponse({"status": "success", "results": discovered})
    except Exception as e:
        logger.error(f"Failed searching groups on Telegram: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/groups/join-and-add")
async def post_join_and_add_group(request: Request, username: str = Form(...)):
    try:
        active_clients = telegram_client.get_active_clients()
        if not active_clients:
            raise ValueError("No active Telegram client connected.")
            
        clean_username = clean_username_input(username)
        if not clean_username:
            raise ValueError("Input username/link is invalid.")
            
        invite_hash = None
        if clean_username.startswith("joinchat/"):
            invite_hash = clean_username.split("/")[-1]
        elif clean_username.startswith("+"):
            invite_hash = clean_username[1:]
            
        joined_any = False
        join_errors = []
        
        for idx, client in enumerate(active_clients):
            try:
                if invite_hash:
                    from telethon.tl.functions.messages import ImportChatInviteRequest
                    from telethon.errors import UserAlreadyParticipantError
                    try:
                        await client(ImportChatInviteRequest(invite_hash))
                        joined_any = True
                    except UserAlreadyParticipantError:
                        joined_any = True
                else:
                    from telethon.tl.functions.channels import JoinChannelRequest
                    await client(JoinChannelRequest(clean_username))
                    joined_any = True
            except Exception as e:
                logger.warning(f"Client #{idx+1} failed to join {clean_username}: {e}")
                join_errors.append(str(e))
                
        if not joined_any and join_errors:
            raise ValueError(f"Failed to join group with any account. Errors: {', '.join(set(join_errors))}")
            
        # Add to local target database
        res = await group_svc.add_group(clean_username)
        if res["status"] == "exists":
            return JSONResponse({"status": "success", "message": "Joined group successfully, but it was already in the database."})
        else:
            return JSONResponse({"status": "success", "message": f"Successfully joined and added group: {res['group']['title']}."})
    except Exception as e:
        logger.error(f"Error in join-and-add: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/templates")
async def get_templates(request: Request):
    # Load override settings first to perform auto-cleanup if expired
    override_active = await settings_svc.get_setting("override_template_active", "0")
    override_until = await settings_svc.get_setting("override_template_until", "")
    
    if override_active == "1" and override_until:
        try:
            if override_until.endswith('Z') or '+' in override_until:
                from datetime import timezone
                iso_str = override_until[:-1] + "+00:00" if override_until.endswith('Z') else override_until
                until_dt = datetime.fromisoformat(iso_str)
                if until_dt.tzinfo is None:
                    until_dt = until_dt.replace(tzinfo=timezone.utc)
                is_expired = datetime.now(timezone.utc) >= until_dt
            else:
                until_dt = datetime.fromisoformat(override_until)
                is_expired = datetime.now() >= until_dt
                
            if is_expired:
                # Expiration hit: auto-cleanup
                await settings_svc.set_setting("override_template_active", "0")
                await settings_svc.set_setting("override_template_until", "")
                await db.execute("DELETE FROM templates WHERE is_override = 1")
                override_active = "0"
                override_until = ""
        except ValueError:
            pass

    templates_list = await template_svc.get_all_templates(is_override=0)
    override_templates = await template_svc.get_all_templates(is_override=1)
    
    # Check if override is currently active in real-time
    is_currently_overridden = False
    if override_active == "1" and override_until:
        try:
            if override_until.endswith('Z') or '+' in override_until:
                from datetime import timezone
                iso_str = override_until[:-1] + "+00:00" if override_until.endswith('Z') else override_until
                until_dt = datetime.fromisoformat(iso_str)
                if until_dt.tzinfo is None:
                    until_dt = until_dt.replace(tzinfo=timezone.utc)
                is_currently_overridden = datetime.now(timezone.utc) < until_dt
            else:
                until_dt = datetime.fromisoformat(override_until)
                is_currently_overridden = datetime.now() < until_dt
        except ValueError:
            pass

    # Get active tab from query params
    active_tab = request.query_params.get("tab", "regular")

    context = {
        "request": request,
        "is_logged_in": True,
        "active_page": "templates",
        "templates": templates_list,
        "override_templates": override_templates,
        "override_active": override_active,
        "override_until": override_until,
        "is_currently_overridden": is_currently_overridden,
        "current_time": datetime.now().isoformat(),
        "active_tab": active_tab,
        **get_flash_context(request)
    }
    return templates.TemplateResponse(request, "templates.html", context)

@app.post("/templates/add")
async def post_add_template(request: Request, text: str = Form(...)):
    try:
        normalized = text.replace("\r\n", "\n")
        import re
        parts = re.split(r'\n\s*---\s*\n', normalized)
        
        added_count = 0
        for part in parts:
            stripped = part.strip()
            if stripped:
                await template_svc.add_template(stripped, is_override=0)
                added_count += 1
                
        if added_count > 1:
            request.session["flash_success"] = f"{added_count} promo templates successfully saved."
        else:
            request.session["flash_success"] = "Promo template successfully saved."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to save promo template: {e}"
        
    return RedirectResponse(url="/templates?tab=regular", status_code=303)

@app.post("/templates/save-override-settings")
async def post_save_override_settings(
    request: Request,
    active: Optional[str] = Form(None),
    until: str = Form(""),
    until_utc: Optional[str] = Form(None)
):
    try:
        is_active = "1" if active else "0"
        
        # Validation checks
        if is_active == "1":
            target_until = until_utc if until_utc else until
            if not target_until:
                raise ValueError("Tanggal kedaluwarsa override harus diisi.")
            try:
                if target_until.endswith('Z') or '+' in target_until:
                    from datetime import timezone
                    iso_str = target_until[:-1] + "+00:00" if target_until.endswith('Z') else target_until
                    until_dt = datetime.fromisoformat(iso_str)
                    if until_dt.tzinfo is None:
                        until_dt = until_dt.replace(tzinfo=timezone.utc)
                    is_expired = until_dt <= datetime.now(timezone.utc)
                else:
                    until_dt = datetime.fromisoformat(target_until)
                    is_expired = until_dt <= datetime.now()

                if is_expired:
                    raise ValueError("Tanggal kedaluwarsa harus di masa depan.")
            except ValueError as ve:
                if "di masa depan" in str(ve):
                    raise
                raise ValueError("Format tanggal tidak valid.")
                
        await settings_svc.set_setting("override_template_active", is_active)
        await settings_svc.set_setting("override_template_until", until_utc if (is_active == "1" and until_utc) else until)
        
        if is_active == "1":
            request.session["flash_success"] = "Mode override promo diaktifkan."
        else:
            request.session["flash_success"] = "Mode override promo dinonaktifkan."
    except Exception as e:
        request.session["flash_danger"] = f"Gagal menyimpan pengaturan override: {e}"
        
    return RedirectResponse(url="/templates?tab=override", status_code=303)

@app.post("/templates/override/add")
async def post_add_override_template(request: Request, text: str = Form(...)):
    try:
        if not text.strip():
            raise ValueError("Teks override tidak boleh kosong.")
            
        normalized = text.replace("\r\n", "\n")
        import re
        parts = re.split(r'\n\s*---\s*\n', normalized)
        
        added_count = 0
        for part in parts:
            stripped = part.strip()
            if stripped:
                await template_svc.add_template(stripped, is_override=1)
                added_count += 1
                
        if added_count > 1:
            request.session["flash_success"] = f"{added_count} temporary override templates successfully added."
        else:
            request.session["flash_success"] = "Template override sementara berhasil ditambahkan."
    except Exception as e:
        request.session["flash_danger"] = f"Gagal menambahkan template override: {e}"
        
    return RedirectResponse(url="/templates?tab=override", status_code=303)

@app.post("/templates/{id}/delete")
async def post_delete_template(request: Request, id: int):
    template = await db.fetchone("SELECT * FROM templates WHERE id = ?", (id,))
    if not template:
        request.session["flash_danger"] = f"Template dengan ID {id} tidak ditemukan."
        return RedirectResponse(url="/templates", status_code=303)

    is_override = template.get("is_override", 0)
    redirect_tab = "override" if is_override == 1 else "regular"

    try:
        # Check if it's a regular template
        if is_override != 1:
            # Check that we have at least one active template remaining in DB
            active_templates = await template_svc.get_active_templates(include_override=False)
            active_ids = {t["id"] for t in active_templates}
            if id in active_ids and len(active_templates) <= 1:
                request.session["flash_danger"] = "Abort: Setidaknya harus ada 1 template regular aktif yang tersisa di sistem."
                return RedirectResponse(url=f"/templates?tab={redirect_tab}", status_code=303)

        await template_svc.delete_template(id)
        request.session["flash_success"] = f"Promo template ID {id} successfully deleted."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to delete template: {e}"
        
    return RedirectResponse(url=f"/templates?tab={redirect_tab}", status_code=303)

@app.post("/templates/{id}/toggle-active")
async def post_toggle_template_active(request: Request, id: int):
    template = await db.fetchone("SELECT * FROM templates WHERE id = ?", (id,))
    if not template:
        request.session["flash_danger"] = f"Template dengan ID {id} tidak ditemukan."
        return RedirectResponse(url="/templates", status_code=303)

    is_override = template.get("is_override", 0)
    redirect_tab = "override" if is_override == 1 else "regular"
    current_active = template.get("is_active", 1)
    new_active = 0 if current_active == 1 else 1

    try:
        # If deactivating a regular template, check that we have at least one active template remaining
        if is_override != 1 and new_active == 0:
            active_templates = await template_svc.get_active_templates(include_override=False)
            if len(active_templates) <= 1:
                request.session["flash_danger"] = "Abort: Setidaknya harus ada 1 template regular aktif yang tersisa di sistem."
                return RedirectResponse(url=f"/templates?tab={redirect_tab}", status_code=303)

        await db.execute("UPDATE templates SET is_active = ?, updated_at = ? WHERE id = ?", (new_active, datetime.now().isoformat(), id))
        status_name = "aktif" if new_active == 1 else "nonaktif"
        request.session["flash_success"] = f"Template ID {id} berhasil di{status_name}kan."
    except Exception as e:
        request.session["flash_danger"] = f"Gagal mengubah status template: {e}"

    return RedirectResponse(url=f"/templates?tab={redirect_tab}", status_code=303)

@app.post("/templates/bulk-action")
async def post_templates_bulk_action(
    request: Request,
    action: str = Form(...),
    ids: str = Form(...),
    tab: str = Form("regular")
):
    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
        if not id_list:
            request.session["flash_danger"] = "Tidak ada template yang dipilih."
            return RedirectResponse(url=f"/templates?tab={tab}", status_code=303)

        if action == "activate":
            for temp_id in id_list:
                await db.execute("UPDATE templates SET is_active = 1, updated_at = ? WHERE id = ?", (datetime.now().isoformat(), temp_id))
            request.session["flash_success"] = f"Berhasil mengaktifkan {len(id_list)} template yang dipilih."
        elif action == "deactivate":
            # Safety check: if tab is regular, we must keep at least one active template in the database
            if tab == "regular":
                all_active = await template_svc.get_active_templates(include_override=False)
                active_ids = {t["id"] for t in all_active}
                to_deactivate = [tid for tid in id_list if tid in active_ids]
                if len(to_deactivate) >= len(active_ids):
                    request.session["flash_danger"] = "Abort: Setidaknya harus ada 1 template regular aktif yang tersisa di sistem."
                    return RedirectResponse(url=f"/templates?tab={tab}", status_code=303)

            for temp_id in id_list:
                await db.execute("UPDATE templates SET is_active = 0, updated_at = ? WHERE id = ?", (datetime.now().isoformat(), temp_id))
            request.session["flash_success"] = f"Berhasil menonaktifkan {len(id_list)} template yang dipilih."
        elif action == "delete":
            # Safety check: if tab is regular, we must keep at least one active template in the database
            if tab == "regular":
                all_active = await template_svc.get_active_templates(include_override=False)
                active_ids = {t["id"] for t in all_active}
                to_delete = [tid for tid in id_list if tid in active_ids]
                if len(to_delete) >= len(active_ids):
                    request.session["flash_danger"] = "Abort: Setidaknya harus ada 1 template regular aktif yang tersisa di sistem."
                    return RedirectResponse(url=f"/templates?tab={tab}", status_code=303)

            for temp_id in id_list:
                await template_svc.delete_template(temp_id)
            request.session["flash_success"] = f"Berhasil menghapus {len(id_list)} template yang dipilih."
        else:
            request.session["flash_danger"] = f"Aksi massal tidak dikenal: {action}"
    except Exception as e:
        request.session["flash_danger"] = f"Gagal menjalankan aksi massal: {e}"

    return RedirectResponse(url=f"/templates?tab={tab}", status_code=303)

@app.get("/settings")
async def get_settings(request: Request):
    settings_dict = await settings_svc.get_all_settings()
    context = {
        "request": request,
        "is_logged_in": True,
        "active_page": "settings",
        "settings": settings_dict,
        **get_flash_context(request)
    }
    return templates.TemplateResponse(request, "settings.html", context)

@app.post("/settings")
async def post_save_settings(
    request: Request,
    min_delay: int = Form(...),
    max_delay: int = Form(...),
    delay_between_groups: int = Form(...),
    send_report: Optional[str] = Form(None),
    report_target: str = Form(...),
    report_frequency: str = Form("every_wave"),
    run_wave_on_start: Optional[str] = Form(None),
    control_group: str = Form(""),
    ghost_auditing_enabled: Optional[str] = Form(None),
    ghost_auditing_limit: int = Form(10),
    ghost_auditing_action: str = Form("skip"),
    auto_responder_enabled: Optional[str] = Form(None),
    auto_responder_text: str = Form(""),
    auto_responder_cooldown: int = Form(24),
    auto_responder_keywords: str = Form(""),
    human_mode_enabled: Optional[str] = Form(None),
    human_mode_sleep_start: str = Form("23:00"),
    human_mode_sleep_end: str = Form("06:00"),
    timezone_offset: str = Form("7"),
    typing_simulation_enabled: Optional[str] = Form(None),
    typing_simulation_min: int = Form(3),
    typing_simulation_max: int = Form(7)
):
    try:
        # Input Validation Checks
        if min_delay < 1:
            raise ValueError("Minimum wave delay must be at least 1 minute.")
        if max_delay <= min_delay:
            raise ValueError("Maximum wave delay must be strictly greater than minimum wave delay.")
        if delay_between_groups < 1:
            raise ValueError("Inter-group delay must be at least 1 second.")
        if not report_target or not report_target.strip():
            raise ValueError("Report and backup target username/ID cannot be empty.")
        if ghost_auditing_limit < 1:
            raise ValueError("Ghost auditing limit must be at least 1 message.")
        if auto_responder_cooldown < 1:
            raise ValueError("Auto-responder cooldown must be at least 1 hour.")
        if typing_simulation_min < 0 or typing_simulation_max < 0:
            raise ValueError("Typing emulation delay must be a positive integer.")
        if typing_simulation_max < typing_simulation_min:
            raise ValueError("Max typing emulation delay must be greater than or equal to min delay.")
            
        if human_mode_enabled is not None:
            try:
                for t in (human_mode_sleep_start, human_mode_sleep_end):
                    parts = t.strip().split(":")
                    if len(parts) != 2:
                        raise ValueError()
                    h, m = int(parts[0]), int(parts[1])
                    if not (0 <= h <= 23 and 0 <= m <= 59):
                        raise ValueError()
            except Exception:
                raise ValueError("Sleep times must be in 24h format like 23:00 or 06:00.")

        await settings_svc.update_all_settings(
            min_delay=min_delay,
            max_delay=max_delay,
            delay_between_groups=delay_between_groups,
            send_report=(send_report is not None),
            report_target=report_target.strip(),
            run_wave_on_start=(run_wave_on_start is not None),
            control_group=control_group,
            ghost_auditing_enabled=(ghost_auditing_enabled is not None),
            ghost_auditing_limit=ghost_auditing_limit,
            ghost_auditing_action=ghost_auditing_action
        )
        
        await settings_svc.set_setting("report_frequency", report_frequency)
        
        await settings_svc.set_setting("auto_responder_enabled", "1" if auto_responder_enabled is not None else "0")
        await settings_svc.set_setting("auto_responder_text", auto_responder_text.strip())
        await settings_svc.set_setting("auto_responder_cooldown", str(auto_responder_cooldown))
        await settings_svc.set_setting("auto_responder_keywords", auto_responder_keywords.strip())
        
        await settings_svc.set_setting("human_mode_enabled", "1" if human_mode_enabled is not None else "0")
        await settings_svc.set_setting("human_mode_sleep_start", human_mode_sleep_start.strip())
        await settings_svc.set_setting("human_mode_sleep_end", human_mode_sleep_end.strip())
        await settings_svc.set_setting("timezone_offset", timezone_offset.strip())
        
        await settings_svc.set_setting("typing_simulation_enabled", "1" if typing_simulation_enabled is not None else "0")
        await settings_svc.set_setting("typing_simulation_min", str(typing_simulation_min))
        await settings_svc.set_setting("typing_simulation_max", str(typing_simulation_max))
        
        # Apply parameters to running state immediately
        state.min_delay = min_delay
        state.max_delay = max_delay
        
        request.session["flash_success"] = "System configurations updated successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to update configurations: {e}"
        
    return RedirectResponse(url="/settings", status_code=303)

@app.get("/logs")
async def get_logs(request: Request, wave_id: Optional[int] = None):
    # Fetch last 15 wave logs
    waves = await db.fetchall("SELECT * FROM wave_logs ORDER BY id DESC LIMIT 15")
    
    items = []
    selected_wave_id = wave_id
    
    if not selected_wave_id and waves:
        selected_wave_id = waves[0]["id"]
        
    if selected_wave_id:
        items = await db.fetchall("SELECT * FROM wave_log_items WHERE wave_log_id = ? ORDER BY id ASC", (selected_wave_id,))
        
    context = {
        "request": request,
        "is_logged_in": True,
        "active_page": "logs",
        "waves": waves,
        "selected_wave_id": selected_wave_id,
        "items": items,
        **get_flash_context(request)
    }
    return templates.TemplateResponse(request, "logs.html", context)

@app.get("/health")
async def get_health(request: Request):
    # Calculate group status counts
    total = len(await group_svc.get_all_groups())
    active = len(await db.fetchall("SELECT id FROM groups WHERE is_skipped = 0 AND status = 'ACTIVE'"))
    skipped = len(await db.fetchall("SELECT id FROM groups WHERE is_skipped = 1 OR status = 'SKIPPED'"))
    flood = len(await db.fetchall("SELECT id FROM groups WHERE status = 'FLOOD_WAIT'"))
    muted = len(await db.fetchall("SELECT id FROM groups WHERE status = 'MUTED'"))
    no_perm = len(await db.fetchall("SELECT id FROM groups WHERE status = 'NO_PERMISSION'"))
    invalid = len(await db.fetchall("SELECT id FROM groups WHERE status = 'INVALID'"))
    failed = len(await db.fetchall("SELECT id FROM groups WHERE status = 'FAILED'"))
    
    # Broken groups (any group not active, skipped, or has fail_streak > 0)
    broken_groups = await db.fetchall(
        """
        SELECT * FROM groups 
        WHERE status NOT IN ('ACTIVE', 'SKIPPED') 
           OR fail_streak > 0 
        ORDER BY status ASC, fail_streak DESC
        """
    )
    
    summary = {
        "total": total,
        "active": active,
        "skipped": skipped,
        "flood": flood,
        "muted": muted,
        "no_perm": no_perm,
        "invalid": invalid,
        "failed": failed
    }
    
    context = {
        "request": request,
        "is_logged_in": True,
        "active_page": "health",
        "summary": summary,
        "broken_groups": broken_groups,
        **get_flash_context(request)
    }
    return templates.TemplateResponse(request, "health.html", context)

@app.post("/health/autoclean")
async def post_autoclean(request: Request):
    remaining = check_action_cooldown("autoclean", cooldown_seconds=30)
    if remaining is not None:
        request.session["flash_danger"] = f"Auto-clean is on cooldown. Please wait {remaining}s."
        return RedirectResponse(url="/health", status_code=303)

    try:
        cleaned_count = await group_svc.autoclean()
        request.session["flash_success"] = f"Auto-clean executed successfully. {cleaned_count} groups auto-skipped."
    except Exception as e:
        request.session["flash_danger"] = f"Auto-clean failed: {e}"
        
    return RedirectResponse(url="/health", status_code=303)

@app.post("/backup/run")
async def post_run_backup(request: Request):
    remaining = check_action_cooldown("backup_run", cooldown_seconds=30)
    if remaining is not None:
        request.session["flash_danger"] = f"Backup run is on cooldown. Please wait {remaining}s."
        return RedirectResponse(url="/settings", status_code=303)

    try:
        backup_paths = await backup_svc.create_backup()
        # Send backup to Telegram
        client = telegram_client.get_client()
        report_target_raw = await settings_svc.get_setting("report_target", config.REPORT_TARGET)
        from utils import resolve_target_entity
        resolved_target = await resolve_target_entity(client, report_target_raw)
        
        for path in backup_paths:
            basename = os.path.basename(path)
            is_gpg = path.endswith(".gpg")
            caption_msg = f"🔒 **Backup: {basename}**\n• **Dibuat**: `{datetime.now().isoformat()}`\n• **Format**: {'🔒 Encrypted GPG' if is_gpg else '⚠️ ZIP Fallback'}"
            await client.send_file(resolved_target, path, caption=caption_msg)
            
            # Clean backup file from local disk to save space
            backup_svc.clean_backup_file(path)
            
        request.session["flash_success"] = f"Backup generated and transmitted {len(backup_paths)} files successfully to {report_target_raw}."
    except Exception as e:
        request.session["flash_danger"] = f"Backup failed: {e}"
        
    return RedirectResponse(url="/settings", status_code=303)

@app.post("/backup/restore")
async def post_restore_backup(
    request: Request,
    backup_file: UploadFile = File(...),
    gpg_password: Optional[str] = Form(None)
):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=303)

    # Save uploaded file temporarily
    temp_upload_dir = Path("temp_uploads")
    temp_upload_dir.mkdir(parents=True, exist_ok=True)
    temp_file_path = temp_upload_dir / backup_file.filename

    try:
        # Write file content
        with open(temp_file_path, "wb") as f:
            content = await backup_file.read()
            f.write(content)

        # Call restore_backup
        await backup_svc.restore_backup(temp_file_path, gpg_password)

        # Hot-reload system
        logger.info("Backup restored. Initiating system hot-reload...")
        
        # 1. Disconnect active clients
        await telegram_client.disconnect_all_clients()
        
        # 2. Re-initialize database
        db.connect()
        await db.initialize_schema()
        
        # 3. Reload settings
        from main import load_settings_into_state
        await load_settings_into_state()
        
        # 4. Start clients and register handlers
        active_clients = await telegram_client.start_all_clients()
        import commands
        await commands.register_handlers(active_clients)
        
        request.session["flash_success"] = "Backup database and session files restored and hot-reloaded successfully!"
    except Exception as e:
        logger.error(f"Failed to restore backup: {e}", exc_info=True)
        request.session["flash_danger"] = f"Restore backup failed: {e}"
    finally:
        # Cleanup temp file
        if temp_file_path.exists():
            temp_file_path.unlink()
        if temp_upload_dir.exists() and not any(temp_upload_dir.iterdir()):
            temp_upload_dir.rmdir()

    return RedirectResponse(url="/settings", status_code=303)

@app.get("/sessions")
async def get_sessions(request: Request):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=303)
        
    session_files = telegram_client.get_session_files()
    default_stem = Path(config.SESSION_NAME).stem
    
    sessions_data = []
    for name in session_files:
        client = telegram_client.get_client(name)
        is_default = (name == default_stem)
        
        authorized = False
        user_details = None
        try:
            # Check authorization state
            if client.is_connected() and await client.is_user_authorized():
                authorized = True
                me = await client.get_me()
                user_details = {
                    "first_name": me.first_name,
                    "username": me.username
                }
        except Exception:
            pass
            
        proxy_row = await db.fetchone("SELECT proxy_url, is_active FROM session_proxies WHERE session_name = ?", (name,))
        proxy_str = proxy_row["proxy_url"] if proxy_row else None
        is_active = proxy_row["is_active"] != 0 if proxy_row and proxy_row["is_active"] is not None else True
            
        sessions_data.append({
            "name": name,
            "is_default": is_default,
            "authorized": authorized,
            "user_details": user_details,
            "proxy": proxy_str,
            "is_active": is_active
        })
        
    context = {
        "request": request,
        "is_logged_in": True,
        "active_page": "sessions",
        "sessions": sessions_data,
        **get_flash_context(request)
    }
    return templates.TemplateResponse(request, "sessions.html", context)

@app.post("/sessions/request-code")
async def post_request_code(request: Request, phone_number: str = Form(...)):
    if not request.session.get("logged_in"):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
        
    phone = phone_number.strip().replace(" ", "")
    if not phone.startswith("+"):
        return JSONResponse({"status": "error", "message": "Phone number must start with '+'"})
        
    try:
        # Clean phone number for safe session filename
        safe_name = phone.replace("+", "")
        client = telegram_client.get_client(safe_name)
        
        await client.connect()
        
        # Clean stale logins
        now = datetime.now()
        for k, v in list(telegram_client.pending_logins.items()):
            if (now - v["created_at"]).total_seconds() > 600:
                try:
                    await v["client"].disconnect()
                except Exception:
                    pass
                telegram_client.pending_logins.pop(k, None)
                
        res = await client.send_code_request(phone)
        
        telegram_client.pending_logins[phone] = {
            "client": client,
            "phone_code_hash": res.phone_code_hash,
            "created_at": now
        }
        
        return JSONResponse({"status": "success", "phone_number": phone})
    except Exception as e:
        logger.error(f"Failed to send code request to {phone}: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)})

@app.post("/sessions/submit-otp")
async def post_submit_otp(
    request: Request, 
    phone_number: str = Form(...), 
    otp_code: str = Form(...),
    two_factor_password: str = Form(None)
):
    if not request.session.get("logged_in"):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
        
    phone = phone_number.strip().replace(" ", "")
    pending = telegram_client.pending_logins.get(phone)
    if not pending:
        return JSONResponse({"status": "error", "message": "Session expired or not found. Please request code again."})
        
    client = pending["client"]
    phone_code_hash = pending["phone_code_hash"]
    
    from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
    try:
        await client.sign_in(
            phone=phone,
            code=otp_code.strip(),
            password=two_factor_password or "",
            phone_code_hash=phone_code_hash
        )
        # Sign in successful! Clean up pending
        telegram_client.pending_logins.pop(phone, None)
        
        # Cache dialogs
        await client.get_dialogs()
        
        # Register command handlers for the new client
        import commands
        await commands.register_handlers([client])
        
        return JSONResponse({"status": "success", "message": "Successfully authenticated!"})
    except SessionPasswordNeededError:
        return JSONResponse({"status": "password_required", "message": "2FA password is required."})
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as err:
        return JSONResponse({"status": "error", "message": f"OTP Error: {err}"})
    except Exception as e:
        logger.error(f"OTP authentication failed for {phone}: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)})

@app.post("/sessions/set-proxy")
async def post_set_proxy(
    request: Request,
    session_name: str = Form(...),
    proxy_url: str = Form("")
):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=303)
        
    proxy_url = proxy_url.strip()
    try:
        if not proxy_url:
            await db.execute("DELETE FROM session_proxies WHERE session_name = ?", (session_name,))
            request.session["flash_success"] = f"Proxy cleared for session '{session_name}'."
        else:
            from urllib.parse import urlparse
            parsed = urlparse(proxy_url)
            if parsed.scheme.lower() not in ('socks5', 'socks4', 'http', 'https') or not parsed.hostname:
                raise ValueError("Invalid proxy format. Must be like: socks5://user:pass@host:port or http://host:port")
                
            now_str = datetime.now().isoformat()
            await db.execute(
                "INSERT OR REPLACE INTO session_proxies (session_name, proxy_url, updated_at) VALUES (?, ?, ?)",
                (session_name, proxy_url, now_str)
            )
            request.session["flash_success"] = f"Proxy successfully updated for session '{session_name}'."

        # Evict and disconnect client from cache to force recreation on next use
        clients_dict = telegram_client.get_clients_dict()
        if session_name in clients_dict:
            client_obj = clients_dict[session_name]
            try:
                if client_obj.is_connected():
                    await client_obj.disconnect()
            except Exception:
                pass
            clients_dict.pop(session_name, None)
            
    except Exception as e:
        request.session["flash_danger"] = f"Failed to set proxy: {e}"
        
    return RedirectResponse(url="/sessions", status_code=303)

@app.post("/sessions/toggle-active")
async def post_toggle_active(
    request: Request,
    session_name: str = Form(...),
    is_active: int = Form(...)
):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=303)
        
    try:
        now_str = datetime.now().isoformat()
        # Find if row exists to keep proxy_url
        row = await db.fetchone("SELECT proxy_url FROM session_proxies WHERE session_name = ?", (session_name,))
        proxy_url = row["proxy_url"] if row else ""
        
        await db.execute("""
            INSERT OR REPLACE INTO session_proxies (session_name, proxy_url, is_active, updated_at)
            VALUES (?, ?, ?, ?)
        """, (session_name, proxy_url, is_active, now_str))
        
        status_text = "diaktifkan" if is_active == 1 else "dinonaktifkan"
        request.session["flash_success"] = f"Bot session '{session_name}' berhasil {status_text}."
    except Exception as e:
        request.session["flash_danger"] = f"Gagal mengubah status aktif session: {e}"
        
    return RedirectResponse(url="/sessions", status_code=303)

@app.post("/sessions/delete")
async def post_delete_session(request: Request, session_name: str = Form(...)):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=303)
        
    default_stem = Path(config.SESSION_NAME).stem
    if session_name == default_stem:
        request.session["flash_danger"] = "Cannot delete the default Master session account."
        return RedirectResponse(url="/sessions", status_code=303)
        
    try:
        clients_dict = telegram_client.get_clients_dict()
        if session_name in clients_dict:
            client = clients_dict[session_name]
            if client.is_connected():
                await client.disconnect()
            clients_dict.pop(session_name, None)
            
        sess_path = Path("sessions") / f"{session_name}.session"
        if sess_path.exists():
            sess_path.unlink()
        journal_path = Path("sessions") / f"{session_name}.session-journal"
        if journal_path.exists():
            journal_path.unlink()
            
        request.session["flash_success"] = f"Session '{session_name}' successfully deleted."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to delete session: {e}"
        
    return RedirectResponse(url="/sessions", status_code=303)

