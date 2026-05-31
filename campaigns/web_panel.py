import logging
import asyncio
import hmac
import secrets
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

import config
from database import db
from utils import state, format_duration
from server_status import get_server_stats
from services.group_service import group_svc
from services.template_service import template_svc
from services.settings_service import settings_svc
from services.wave_service import wave_svc
from services.backup_service import backup_svc
import telegram_client

logger = logging.getLogger("WebPanel")

# Initialize FastAPI App
app = FastAPI(title="Userbot Control Panel", docs_url=None, redoc_url=None)

# Add Session Middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=config.WEB_SESSION_SECRET,
    session_cookie="userbot_session",
    max_age=3600 * 24 # 1 day session
)

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
    return templates.TemplateResponse("login.html", context)

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
    return templates.TemplateResponse("dashboard.html", context)

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
    return templates.TemplateResponse("groups.html", context)

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

@app.get("/templates")
async def get_templates(request: Request):
    templates_list = await template_svc.get_all_templates()
    context = {
        "request": request,
        "is_logged_in": True,
        "active_page": "templates",
        "templates": templates_list,
        **get_flash_context(request)
    }
    return templates.TemplateResponse("templates.html", context)

@app.post("/templates/add")
async def post_add_template(request: Request, text: str = Form(...)):
    try:
        await template_svc.add_template(text)
        request.session["flash_success"] = "Promo template successfully saved."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to save promo template: {e}"
        
    return RedirectResponse(url="/templates", status_code=303)

@app.post("/templates/{id}/delete")
async def post_delete_template(request: Request, id: int):
    template = await db.fetchone("SELECT * FROM templates WHERE id = ?", (id,))
    if not template:
        request.session["flash_danger"] = f"Template with ID {id} not found."
        return RedirectResponse(url="/templates", status_code=303)

    try:
        # Check that we have at least one active template remaining
        active_templates = await template_svc.get_active_templates()
        if len(active_templates) <= 1:
            request.session["flash_danger"] = "Abort: At least one active promotion template must remain in the system."
        else:
            await template_svc.delete_template(id)
            request.session["flash_success"] = f"Promo template ID {id} successfully deleted."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to delete template: {e}"
        
    return RedirectResponse(url="/templates", status_code=303)

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
    return templates.TemplateResponse("settings.html", context)

@app.post("/settings")
async def post_save_settings(
    request: Request,
    min_delay: int = Form(...),
    max_delay: int = Form(...),
    delay_between_groups: int = Form(...),
    send_report: Optional[str] = Form(None),
    report_target: str = Form(...),
    run_wave_on_start: Optional[str] = Form(None)
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
            
        await settings_svc.update_all_settings(
            min_delay=min_delay,
            max_delay=max_delay,
            delay_between_groups=delay_between_groups,
            send_report=(send_report is not None),
            report_target=report_target.strip(),
            run_wave_on_start=(run_wave_on_start is not None)
        )
        
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
    return templates.TemplateResponse("logs.html", context)

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
    return templates.TemplateResponse("health.html", context)

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
        backup_path = await backup_svc.create_backup()
        # Send backup to Telegram
        client = telegram_client.get_client()
        report_target = await settings_svc.get_setting("report_target", config.REPORT_TARGET)
        if isinstance(report_target, str):
            cleaned_tgt = report_target.strip()
            if cleaned_tgt.replace("-", "").isdigit():
                report_target = int(cleaned_tgt)
        
        caption_msg = f"🔒 **Backup Proyek Terenkripsi GPG**\n• **Dibuat**: `{datetime.now().isoformat()}`\n• **Berkas**: `{backup_path.split(chr(92))[-1]}`"
        await client.send_file(report_target, backup_path, caption=caption_msg)
        
        # Clean backup file from local disk to save space
        backup_svc.clean_backup_file(backup_path)
        
        request.session["flash_success"] = f"Encrypted backup generated and transmitted to {report_target}."
    except Exception as e:
        request.session["flash_danger"] = f"Backup failed: {e}"
        
    return RedirectResponse(url="/settings", status_code=303)
