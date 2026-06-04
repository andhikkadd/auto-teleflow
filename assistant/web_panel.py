import logging
import secrets
import hmac
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import config
from database import db
from services.product_service import product_svc
from services.faq_service import faq_svc
from services.lead_service import lead_svc
from services.settings_service import settings_svc
from services.ai_service import AIService

logger = logging.getLogger("WebPanel")

app = FastAPI(title="Otan Assistant Admin Panel")

# Add Session Middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=config.WEB_SESSION_SECRET,
    session_cookie="assistant_session",
    max_age=3600 * 24  # 1 day session
)

def inject_csrf(request: Request):
    # Ensure a CSRF token exists for the session
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_hex(32)
    return {"csrf_token": request.session["csrf_token"]}

# Setup Templates and Static files
templates = Jinja2Templates(
    directory="templates",
    context_processors=[inject_csrf]
)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Custom Exceptions for Authentication
class NotAuthenticatedException(Exception):
    pass

@app.exception_handler(NotAuthenticatedException)
async def auth_exception_handler(request: Request, exc: NotAuthenticatedException):
    request.session["flash_danger"] = "Please login to access the administration panel."
    return RedirectResponse(url="/login", status_code=303)

# Dependency to check login status
async def require_login(request: Request):
    if not request.session.get("logged_in"):
        raise NotAuthenticatedException()

# Dependency to verify CSRF token on POST requests
async def verify_csrf(request: Request):
    if request.method == "POST":
        form_data = await request.form()
        token = form_data.get("csrf_token")
        session_token = request.session.get("csrf_token")
        if not token or not session_token or not hmac.compare_digest(token, session_token):
            raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")

# Context processor for templates to read request session vars
def global_vars_processor(request: Request):
    flash_success = None
    flash_danger = None
    logged_in = False
    
    if "session" in request.scope:
        flash_success = request.session.pop("flash_success", None)
        flash_danger = request.session.pop("flash_danger", None)
        logged_in = request.session.get("logged_in", False)
        
    return {
        "flash_success": flash_success,
        "flash_danger": flash_danger,
        "logged_in": logged_in,
        "admin_username": config.WEB_ADMIN_USERNAME
    }

templates.context_processors.append(global_vars_processor)

# --- Routes ---

@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    if request.session.get("logged_in"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html")

@app.post("/login")
async def post_login(request: Request, username: str = Form(...), password: str = Form(...), token_verify=Depends(verify_csrf)):
    # Constant-time comparison to prevent timing attacks
    user_ok = hmac.compare_digest(username.encode("utf-8"), config.WEB_ADMIN_USERNAME.encode("utf-8"))
    pass_ok = hmac.compare_digest(password.encode("utf-8"), config.WEB_ADMIN_PASSWORD.encode("utf-8"))
    
    if user_ok and pass_ok:
        request.session["logged_in"] = True
        request.session["flash_success"] = "Welcome back, Admin!"
        return RedirectResponse(url="/", status_code=303)
        
    request.session["flash_danger"] = "Invalid username or password."
    return RedirectResponse(url="/login", status_code=303)

@app.get("/logout")
async def get_logout(request: Request):
    request.session.clear()
    request.session["flash_success"] = "You have been logged out."
    return RedirectResponse(url="/login", status_code=303)

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def get_dashboard(request: Request):
    prod_count = len(await product_svc.get_all_products())
    alias_count = len(await product_svc.get_all_aliases())
    faq_count = len(await faq_svc.get_all_faqs())
    business_name = await settings_svc.get_setting("business_name", config.BUSINESS_NAME)
    
    # Get telemetry data for charts
    daily_stats = await lead_svc.get_daily_usage_stats(7)
    intent_breakdown = await lead_svc.get_intent_breakdown()
    
    return templates.TemplateResponse(request, "dashboard.html", {
        "prod_count": prod_count,
        "alias_count": alias_count,
        "faq_count": faq_count,
        "business_name": business_name,
        "daily_stats": daily_stats,
        "intent_breakdown": intent_breakdown
    })

@app.get("/products", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def get_products(request: Request):
    products = await product_svc.get_all_products()
    products_with_variants = []
    for p in products:
        p_dict = dict(p)
        p_dict["variants"] = await product_svc.get_variants_for_product(p["id"])
        products_with_variants.append(p_dict)
    return templates.TemplateResponse(request, "products.html", {"products": products_with_variants})

@app.post("/products/add", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_products_add(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    is_active: int = Form(1),
    autoorder_supported: int = Form(0),
    autoorder_bot_username: str = Form(""),
    autoorder_bot_link: str = Form(""),
    sales_note: str = Form(""),
    requirement_note: str = Form(""),
    process_note: str = Form(""),
    warranty_note: str = Form(""),
    restriction_note: str = Form(""),
    variant_name: list = Form(default=[]),
    variant_price: list = Form(default=[]),
    variant_note: list = Form(default=[]),
    variant_is_active: list = Form(default=[])
):
    try:
        product_id = await product_svc.add_product(
            name=name.strip(),
            category="",
            description=description.strip(),
            inquiry_note="",
            is_active=is_active,
            autoorder_supported=autoorder_supported,
            autoorder_bot_username=autoorder_bot_username.strip(),
            autoorder_bot_link=autoorder_bot_link.strip(),
            sales_note=sales_note.strip(),
            requirement_note=requirement_note.strip(),
            process_note=process_note.strip(),
            warranty_note=warranty_note.strip(),
            restriction_note=restriction_note.strip()
        )
        
        # Save packages/variants
        packages_list = []
        for i in range(len(variant_name)):
            p_name = variant_name[i].strip()
            if not p_name:
                continue
            try:
                p_val = int(variant_price[i]) if i < len(variant_price) else 0
            except ValueError:
                p_val = 0
            p_note = variant_note[i].strip() if i < len(variant_note) else ""
            p_active = 1
            if variant_is_active and i < len(variant_is_active):
                try:
                    p_active = int(variant_is_active[i])
                except ValueError:
                    p_active = 1
            packages_list.append((p_name, "", p_val, "", "", p_note, p_active))
            
        await product_svc.update_packages(product_id, packages_list)
        request.session["flash_success"] = f"Product '{name}' added successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to add product: {e}"
        
    return RedirectResponse(url="/products", status_code=303)

@app.post("/products/edit/{product_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_products_edit(
    product_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    is_active: int = Form(1),
    autoorder_supported: int = Form(0),
    autoorder_bot_username: str = Form(""),
    autoorder_bot_link: str = Form(""),
    sales_note: str = Form(""),
    requirement_note: str = Form(""),
    process_note: str = Form(""),
    warranty_note: str = Form(""),
    restriction_note: str = Form(""),
    variant_name: list = Form(default=[]),
    variant_price: list = Form(default=[]),
    variant_note: list = Form(default=[]),
    variant_is_active: list = Form(default=[])
):
    try:
        await product_svc.update_product(
            product_id=product_id,
            name=name.strip(),
            category="",
            description=description.strip(),
            inquiry_note="",
            is_active=is_active,
            autoorder_supported=autoorder_supported,
            autoorder_bot_username=autoorder_bot_username.strip(),
            autoorder_bot_link=autoorder_bot_link.strip(),
            sales_note=sales_note.strip(),
            requirement_note=requirement_note.strip(),
            process_note=process_note.strip(),
            warranty_note=warranty_note.strip(),
            restriction_note=restriction_note.strip()
        )
        
        # Save packages/variants
        packages_list = []
        for i in range(len(variant_name)):
            p_name = variant_name[i].strip()
            if not p_name:
                continue
            try:
                p_val = int(variant_price[i]) if i < len(variant_price) else 0
            except ValueError:
                p_val = 0
            p_note = variant_note[i].strip() if i < len(variant_note) else ""
            p_active = 1
            if variant_is_active and i < len(variant_is_active):
                try:
                    p_active = int(variant_is_active[i])
                except ValueError:
                    p_active = 1
            packages_list.append((p_name, "", p_val, "", "", p_note, p_active))
            
        await product_svc.update_packages(product_id, packages_list)
        request.session["flash_success"] = f"Product updated successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to update product: {e}"
        
    return RedirectResponse(url="/products", status_code=303)

@app.post("/products/delete/{product_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_products_delete(product_id: int, request: Request):
    try:
        await product_svc.delete_product(product_id)
        request.session["flash_success"] = "Product deleted successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to delete product: {e}"
        
    return RedirectResponse(url="/products", status_code=303)

@app.post("/products/toggle-status/{product_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_products_toggle_status(product_id: int, request: Request):
    try:
        new_status = await product_svc.toggle_product_active(product_id)
        status_str = "Active" if new_status == 1 else "Disabled"
        request.session["flash_success"] = f"Product status updated to {status_str}."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to toggle product status: {e}"
        
    return RedirectResponse(url="/products", status_code=303)

@app.get("/responses", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def get_responses(request: Request, active_tab: str = "faq"):
    aliases = await product_svc.get_all_aliases()
    products = await product_svc.get_active_products()
    faqs = await faq_svc.get_all_faqs()
    return templates.TemplateResponse(request, "responses.html", {
        "aliases": aliases,
        "products": products,
        "faqs": faqs,
        "active_tab": active_tab
    })

@app.post("/aliases/add", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_aliases_add(request: Request, product_id: int = Form(...), alias_text: str = Form(...)):
    try:
        await product_svc.add_alias(product_id, alias_text)
        request.session["flash_success"] = f"Alias '{alias_text}' added successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to add alias: {e}"
        
    return RedirectResponse(url="/responses?active_tab=aliases", status_code=303)

@app.post("/aliases/delete/{alias_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_aliases_delete(alias_id: int, request: Request):
    try:
        await product_svc.delete_alias(alias_id)
        request.session["flash_success"] = "Alias deleted successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to delete alias: {e}"
        
    return RedirectResponse(url="/responses?active_tab=aliases", status_code=303)

@app.post("/faq/edit/{intent}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_faq_edit(
    intent: str,
    request: Request,
    answer: str = Form(...),
    keywords: str = Form(""),
    is_active: int = Form(1),
    buttons: str = Form("")
):
    try:
        if intent in ("welcome", "help", "fallback"):
            await faq_svc.update_faq(intent, answer.strip(), None, is_active, buttons.strip())
        else:
            await faq_svc.update_faq(intent, answer.strip(), keywords.strip(), is_active, buttons.strip())
        request.session["flash_success"] = f"FAQ template '{intent}' updated successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to update FAQ: {e}"
        
    return RedirectResponse(url="/responses?active_tab=faq", status_code=303)

@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def get_settings(request: Request):
    business_name = await settings_svc.get_setting("business_name", config.BUSINESS_NAME)
    wa_link = await settings_svc.get_setting("wa_link", config.WA_LINK)
    channel_link = await settings_svc.get_setting("channel_link", config.CHANNEL_LINK)
    autoorder_bot_username = await settings_svc.get_setting("autoorder_bot_username", config.AUTOORDER_BOT_USERNAME)
    autoorder_bot_link = await settings_svc.get_setting("autoorder_bot_link", config.AUTOORDER_BOT_LINK)
    
    default_welcome = (
        "Halo kak! Selamat datang di **{business_name}** 👋\n\n"
        "Saya **Otan**, asisten front-desk toko kami. Otan siap membantu menjawab "
        "ketersediaan aplikasi premium, info cara beli, payment, dan garansi.\n\n"
        "Silakan gunakan menu tombol di bawah ini ya kak!"
    )
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
    
    return templates.TemplateResponse(request, "settings.html", {
        "business_name": business_name,
        "wa_link": wa_link,
        "channel_link": channel_link,
        "autoorder_bot_username": autoorder_bot_username,
        "autoorder_bot_link": autoorder_bot_link
    })

@app.post("/settings", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_settings(
    request: Request,
    business_name: str = Form(...),
    wa_link: str = Form(""),
    channel_link: str = Form(""),
    autoorder_bot_username: str = Form(""),
    autoorder_bot_link: str = Form("")
):
    try:
        await settings_svc.update_all_settings(
            business_name=business_name.strip(),
            wa_link=wa_link.strip(),
            channel_link=channel_link.strip(),
            autoorder_bot_username=autoorder_bot_username.strip(),
            autoorder_bot_link=autoorder_bot_link.strip()
        )
        request.session["flash_success"] = "Configurations updated successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to update settings: {e}"
        
    return RedirectResponse(url="/settings", status_code=303)



@app.get("/ai-settings", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def get_ai_settings(request: Request):
    ai_enabled = await settings_svc.get_setting("ai_enabled", "true")
    gemini_model = await settings_svc.get_setting("gemini_model", "gemini-2.5-flash")
    ai_temperature = await settings_svc.get_setting("ai_temperature", "0.7")
    ai_timeout = await settings_svc.get_setting("ai_timeout_seconds", "8")
    ai_max_user = await settings_svc.get_setting("ai_max_calls_per_user_per_day", "30")
    ai_max_global = await settings_svc.get_setting("ai_daily_global_limit", "1000")
    ai_style_strength = await settings_svc.get_setting("ai_style_strength", "medium")
    
    # Check if API key is set
    has_api_key = bool((await settings_svc.get_setting("gemini_api_key", "")).strip() or os.getenv("GEMINI_API_KEY", "").strip())
    
    # Get recent usage logs
    recent_errors = await AIService.get_recent_errors(10)
    usage_today = await AIService.get_usage_today()
    
    # Get active products for testing dropdown
    active_products = await product_svc.get_active_products()
    
    # Persona settings
    bot_display_name = await settings_svc.get_setting("bot_display_name", "Otan")
    bot_role_desc = await settings_svc.get_setting("bot_role_desc", "Kamu adalah asisten front-desk CS di toko produk digital premium.")
    bot_tone_style = await settings_svc.get_setting("bot_tone_style", "friendly, casual-professional, helpful, warm, tidak kaku, santai tapi sopan")
    bot_emoji_level = await settings_svc.get_setting("bot_emoji_level", "medium")
    bot_humor_level = await settings_svc.get_setting("bot_humor_level", "medium")
    bot_reply_length = await settings_svc.get_setting("bot_reply_length", "medium")
    price_answer_mode = await settings_svc.get_setting("price_answer_mode", "exact_only")
    out_of_scope_mode = await settings_svc.get_setting("out_of_scope_mode", "redirect")
    
    return templates.TemplateResponse(request, "ai_settings.html", {
        "ai_enabled": ai_enabled,
        "gemini_model": gemini_model,
        "ai_temperature": ai_temperature,
        "ai_timeout": ai_timeout,
        "ai_max_user": ai_max_user,
        "ai_max_global": ai_max_global,
        "ai_style_strength": ai_style_strength,
        "active_products": active_products,
        "has_api_key": has_api_key,
        "recent_errors": recent_errors,
        "usage_today": usage_today,
        
        "bot_display_name": bot_display_name,
        "bot_role_desc": bot_role_desc,
        "bot_tone_style": bot_tone_style,
        "bot_emoji_level": bot_emoji_level,
        "bot_humor_level": bot_humor_level,
        "bot_reply_length": bot_reply_length,
        "price_answer_mode": price_answer_mode,
        "out_of_scope_mode": out_of_scope_mode
    })

@app.post("/ai-settings", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_ai_settings(
    request: Request,
    ai_enabled: str = Form("false"),
    gemini_api_key: str = Form(""),
    gemini_model: str = Form(...),
    ai_temperature: str = Form("0.7"),
    ai_timeout: str = Form("8"),
    ai_max_user: str = Form("30"),
    ai_max_global: str = Form("1000"),
    ai_style_strength: str = Form("medium")
):
    try:
        await settings_svc.set_setting("ai_enabled", ai_enabled)
        await settings_svc.set_setting("gemini_model", gemini_model.strip())
        await settings_svc.set_setting("ai_temperature", ai_temperature.strip())
        await settings_svc.set_setting("ai_timeout_seconds", ai_timeout.strip())
        await settings_svc.set_setting("ai_max_calls_per_user_per_day", ai_max_user.strip())
        await settings_svc.set_setting("ai_daily_global_limit", ai_max_global.strip())
        await settings_svc.set_setting("ai_style_strength", ai_style_strength.strip())
        
        # Only update key if not empty (prevent clearing existing key)
        if gemini_api_key.strip():
            await settings_svc.set_setting("gemini_api_key", gemini_api_key.strip())
            
        request.session["flash_success"] = "AI Configurations updated successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to update AI configurations: {e}"
        
    return RedirectResponse(url="/ai-settings", status_code=303)

@app.get("/persona", dependencies=[Depends(require_login)])
async def get_persona(request: Request):
    return RedirectResponse(url="/ai-settings", status_code=303)

@app.post("/persona", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_persona(
    request: Request,
    bot_display_name: str = Form(...),
    bot_role_desc: str = Form(...),
    bot_tone_style: str = Form(...),
    bot_emoji_level: str = Form(...),
    bot_humor_level: str = Form(...),
    bot_reply_length: str = Form(...),
    price_answer_mode: str = Form(...),
    out_of_scope_mode: str = Form(...)
):
    try:
        await settings_svc.set_setting("bot_display_name", bot_display_name.strip())
        await settings_svc.set_setting("bot_role_desc", bot_role_desc.strip())
        await settings_svc.set_setting("bot_tone_style", bot_tone_style.strip())
        await settings_svc.set_setting("bot_emoji_level", bot_emoji_level.strip())
        await settings_svc.set_setting("bot_humor_level", bot_humor_level.strip())
        await settings_svc.set_setting("bot_reply_length", bot_reply_length.strip())
        await settings_svc.set_setting("price_answer_mode", price_answer_mode.strip())
        await settings_svc.set_setting("out_of_scope_mode", out_of_scope_mode.strip())
        
        request.session["flash_success"] = "Bot Persona updated successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to update Bot Persona: {e}"
        
    return RedirectResponse(url="/ai-settings", status_code=303)

@app.post("/ai-settings/test", dependencies=[Depends(require_login)])
async def post_ai_settings_test(
    request: Request,
    message_text: str = Form(...),
    product_id: str = Form("auto")
):
    try:
        from services.bot_flow_service import BotFlowService
        from services.ai_service import AIService
        
        user_id = 999999999  # Mock user ID for testing
        normalized_query = message_text.strip().lower()
        
        # Determine product matching
        if product_id == "auto":
            # Match product using bot flow logic
            session = {"telegram_user_id": user_id, "last_product_id": None, "last_intent": None, "last_topic": None}
            product, match_method = await BotFlowService.match_product(message_text, session)
        elif product_id == "none" or not product_id:
            product = None
            match_method = "manual_none"
        else:
            product = await product_svc.get_product_by_id(int(product_id))
            match_method = "manual"
            
        product_info = product["name"] if product else "None"
        
        # Compile DB context
        db_context = await BotFlowService.compile_db_context(product)
        
        # Get AI config details
        api_key = await AIService.get_api_key()
        model_name = await AIService.get_model()
        
        if not api_key:
            return {
                "success": False,
                "error": "Gemini API key is not configured. Please enter a API key first."
            }
            
        # Call AI
        ai_res = await AIService.generate_reply(user_id, normalized_query, message_text, db_context)
        
        return {
            "success": True,
            "match_method": match_method,
            "matched_product": product_info,
            "db_context": db_context,
            "model_used": model_name,
            "ai_response": ai_res
        }
    except Exception as e:
        logger.error(f"Error testing AI query: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/packages", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def get_packages(request: Request, product_id: int = None):
    if not product_id:
        return RedirectResponse(url="/products", status_code=303)
    product = await product_svc.get_product_by_id(product_id)
    if not product:
        request.session["flash_danger"] = "Product not found."
        return RedirectResponse(url="/products", status_code=303)
    packages = await product_svc.get_packages_for_product(product_id)
    return templates.TemplateResponse(request, "packages.html", {
        "product": product,
        "packages": packages
    })

@app.post("/packages/add/{product_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_packages_add(
    product_id: int,
    request: Request,
    package_name: str = Form(...),
    duration: str = Form(""),
    price: int = Form(...),
    warranty_label: str = Form(""),
    warranty_detail: str = Form(""),
    notes: str = Form(""),
    is_active: int = Form(1)
):
    try:
        now_str = datetime.now().isoformat()
        await db.execute(
            """
            INSERT INTO product_packages (product_id, package_name, duration, price, warranty_label, warranty_detail, notes, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, package_name.strip(), duration.strip(), price, warranty_label.strip(), warranty_detail.strip(), notes.strip(), is_active, now_str, now_str)
        )
        request.session["flash_success"] = f"Package '{package_name}' added successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to add package: {e}"
    return RedirectResponse(url=f"/packages?product_id={product_id}", status_code=303)

@app.post("/packages/edit/{product_id}/{package_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_packages_edit(
    product_id: int,
    package_id: int,
    request: Request,
    package_name: str = Form(...),
    duration: str = Form(""),
    price: int = Form(...),
    warranty_label: str = Form(""),
    warranty_detail: str = Form(""),
    notes: str = Form(""),
    is_active: int = Form(1)
):
    try:
        now_str = datetime.now().isoformat()
        await db.execute(
            """
            UPDATE product_packages
            SET package_name = ?, duration = ?, price = ?, warranty_label = ?, warranty_detail = ?, notes = ?, is_active = ?, updated_at = ?
            WHERE id = ? AND product_id = ?
            """,
            (package_name.strip(), duration.strip(), price, warranty_label.strip(), warranty_detail.strip(), notes.strip(), is_active, now_str, package_id, product_id)
        )
        request.session["flash_success"] = "Package updated successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to update package: {e}"
    return RedirectResponse(url=f"/packages?product_id={product_id}", status_code=303)

@app.post("/packages/delete/{product_id}/{package_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_packages_delete(product_id: int, package_id: int, request: Request):
    try:
        await db.execute("DELETE FROM product_packages WHERE id = ? AND product_id = ?", (package_id, product_id))
        request.session["flash_success"] = "Package deleted successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to delete package: {e}"
    return RedirectResponse(url=f"/packages?product_id={product_id}", status_code=303)

@app.post("/packages/toggle/{product_id}/{package_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_packages_toggle(product_id: int, package_id: int, request: Request):
    try:
        row = await db.fetchone("SELECT is_active FROM product_packages WHERE id = ?", (package_id,))
        if row:
            new_val = 0 if row["is_active"] == 1 else 1
            now_str = datetime.now().isoformat()
            await db.execute(
                "UPDATE product_packages SET is_active = ?, updated_at = ? WHERE id = ?",
                (new_val, now_str, package_id)
            )
            request.session["flash_success"] = "Package status toggled."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to toggle status: {e}"
    return RedirectResponse(url=f"/packages?product_id={product_id}", status_code=303)

@app.get("/product-faqs", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def get_product_faqs(request: Request, product_id: int = None):
    if not product_id:
        return RedirectResponse(url="/products", status_code=303)
    product = await product_svc.get_product_by_id(product_id)
    if not product:
        request.session["flash_danger"] = "Product not found."
        return RedirectResponse(url="/products", status_code=303)
    faqs = await product_svc.get_faqs_for_product(product_id)
    return templates.TemplateResponse(request, "product_faq.html", {
        "product": product,
        "faqs": faqs
    })

@app.post("/product-faqs/add/{product_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_product_faqs_add(
    product_id: int,
    request: Request,
    question: str = Form(...),
    keywords: str = Form(""),
    answer: str = Form(...),
    is_active: int = Form(1)
):
    try:
        await product_svc.add_product_faq(product_id, question, keywords, answer, is_active)
        request.session["flash_success"] = "Product FAQ added successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to add FAQ: {e}"
    return RedirectResponse(url=f"/product-faqs?product_id={product_id}", status_code=303)

@app.post("/product-faqs/edit/{product_id}/{faq_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_product_faqs_edit(
    product_id: int,
    faq_id: int,
    request: Request,
    question: str = Form(...),
    keywords: str = Form(""),
    answer: str = Form(...),
    is_active: int = Form(1)
):
    try:
        await product_svc.update_product_faq(faq_id, question, keywords, answer, is_active)
        request.session["flash_success"] = "Product FAQ updated successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to update FAQ: {e}"
    return RedirectResponse(url=f"/product-faqs?product_id={product_id}", status_code=303)

@app.post("/product-faqs/delete/{product_id}/{faq_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_product_faqs_delete(product_id: int, faq_id: int, request: Request):
    try:
        await product_svc.delete_product_faq(faq_id)
        request.session["flash_success"] = "Product FAQ deleted successfully."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to delete FAQ: {e}"
    return RedirectResponse(url=f"/product-faqs?product_id={product_id}", status_code=303)

@app.post("/product-faqs/toggle/{product_id}/{faq_id}", dependencies=[Depends(require_login), Depends(verify_csrf)])
async def post_product_faqs_toggle(product_id: int, faq_id: int, request: Request):
    try:
        row = await db.fetchone("SELECT is_active FROM product_faqs WHERE id = ?", (faq_id,))
        if row:
            new_val = 0 if row["is_active"] == 1 else 1
            now_str = datetime.now().isoformat()
            await db.execute(
                "UPDATE product_faqs SET is_active = ?, updated_at = ? WHERE id = ?",
                (new_val, now_str, faq_id)
            )
            request.session["flash_success"] = "FAQ status toggled."
    except Exception as e:
        request.session["flash_danger"] = f"Failed to toggle status: {e}"
    return RedirectResponse(url=f"/product-faqs?product_id={product_id}", status_code=303)

@app.get("/orders", dependencies=[Depends(require_login)])
async def get_orders(request: Request):
    return RedirectResponse(url="/", status_code=303)

@app.get("/tickets", dependencies=[Depends(require_login)])
async def get_tickets(request: Request):
    return RedirectResponse(url="/", status_code=303)

@app.get("/templates", dependencies=[Depends(require_login)])
async def redirect_templates():
    return RedirectResponse(url="/faq", status_code=303)

@app.get("/logs", dependencies=[Depends(require_login)])
async def redirect_logs():
    return RedirectResponse(url="/", status_code=303)

async def run_server():
    """Starts Uvicorn server in the running event loop."""
    import uvicorn
    logger.info(f"Starting FastAPI Web Admin Panel on {config.WEB_HOST}:{config.WEB_PORT}...")
    server_config = uvicorn.Config(
        app=app,
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(server_config)
    await server.serve()
