import os
import httpx
import logging
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.background import BackgroundTask
from dotenv import load_dotenv, dotenv_values

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("PortalGateway")

app = FastAPI(title="Auto-Teleflow Portal")

# Configs
PORTAL_HOST = os.getenv("PORTAL_HOST", "0.0.0.0").strip()
try:
    PORTAL_PORT = int(os.getenv("PORTAL_PORT") or os.getenv("SERVER_PORT") or "4765")
except ValueError:
    PORTAL_PORT = 4765

# Load sub-app configurations to resolve internal ports dynamically
camp_env = dotenv_values("campaigns/.env")
asst_env = dotenv_values("assistant/.env")

campaigns_host = camp_env.get("WEB_HOST") or "127.0.0.1"
campaigns_port = camp_env.get("WEB_PORT") or "8000"
CAMPAIGNS_URL = os.getenv("CAMPAIGNS_URL", f"http://{campaigns_host}:{campaigns_port}").strip()

assistant_host = asst_env.get("WEB_HOST") or "127.0.0.1"
assistant_port = asst_env.get("WEB_PORT") or "8001"
ASSISTANT_URL = os.getenv("ASSISTANT_URL", f"http://{assistant_host}:{assistant_port}").strip()

SESSION_SECRET = os.getenv("PORTAL_SESSION_SECRET", "auto-teleflow-portal-secret-key-98721").strip()

# Add Session Middleware for portal panel selection state
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="portal_session",
    max_age=3600 * 24  # 1 day session
)

# Async HTTP Client for proxying
client = httpx.AsyncClient(timeout=60.0)

# Beautiful portal HTML template using premium dark/cyberpunk styles
PORTAL_HTML = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Auto-Teleflow Unified Portal</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0f172a;
            --bg-card: rgba(30, 41, 59, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --primary-glow: rgba(99, 102, 241, 0.15);
            --accent-purple: #818cf8;
            --accent-cyan: #38bdf8;
            --text-main: #f8fafc;
            --text-secondary: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background: radial-gradient(circle at 50% 50%, #1e1b4b 0%, #0f172a 100%);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2rem;
            overflow-x: hidden;
        }

        .container {
            max-width: 1000px;
            width: 100%;
            text-align: center;
        }

        header {
            margin-bottom: 3.5rem;
        }

        h1 {
            font-size: 2.8rem;
            font-weight: 700;
            letter-spacing: -0.05rem;
            margin-bottom: 0.75rem;
            background: linear-gradient(135deg, #a5b4fc 0%, #38bdf8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 4px 20px var(--primary-glow);
        }

        .subtitle {
            font-size: 1.1rem;
            color: var(--text-secondary);
            font-weight: 300;
            max-width: 600px;
            margin: 0 auto;
        }

        .cards-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2.5rem;
            margin-bottom: 4rem;
        }

        @media (max-width: 768px) {
            .cards-grid {
                grid-template-columns: 1fr;
                gap: 2rem;
            }
        }

        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 3rem 2rem;
            backdrop-filter: blur(16px);
            transition: all 0.4s cubic-bezier(0.165, 0.84, 0.44, 1);
            position: relative;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
        }

        .card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(180deg, rgba(255,255,255,0.03) 0%, transparent 100%);
            pointer-events: none;
        }

        .card-campaigns:hover {
            transform: translateY(-8px);
            border-color: rgba(129, 140, 248, 0.4);
            box-shadow: 0 20px 40px rgba(129, 140, 248, 0.15);
        }

        .card-assistant:hover {
            transform: translateY(-8px);
            border-color: rgba(56, 189, 248, 0.4);
            box-shadow: 0 20px 40px rgba(56, 189, 248, 0.15);
        }

        .icon {
            font-size: 3.5rem;
            margin-bottom: 1.5rem;
            filter: drop-shadow(0 8px 16px rgba(0,0,0,0.2));
        }

        .card h2 {
            font-size: 1.6rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }

        .card-campaigns h2 {
            color: #c7d2fe;
        }

        .card-assistant h2 {
            color: #bae6fd;
        }

        .card-tag {
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05rem;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            margin-bottom: 1.5rem;
        }

        .card-campaigns .card-tag {
            background: rgba(129, 140, 248, 0.1);
            color: var(--accent-purple);
            border: 1px solid rgba(129, 140, 248, 0.2);
        }

        .card-assistant .card-tag {
            background: rgba(56, 189, 248, 0.1);
            color: var(--accent-cyan);
            border: 1px solid rgba(56, 189, 248, 0.2);
        }

        .card p {
            color: var(--text-secondary);
            font-size: 0.95rem;
            line-height: 1.6;
            margin-bottom: 2.5rem;
            max-width: 320px;
        }

        .btn {
            display: inline-block;
            width: 100%;
            max-width: 240px;
            padding: 0.9rem 2rem;
            border-radius: 12px;
            font-weight: 600;
            text-decoration: none;
            font-size: 0.95rem;
            transition: all 0.3s ease;
            text-align: center;
        }

        .btn-campaigns {
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
        }

        .btn-campaigns:hover {
            background: linear-gradient(135deg, #818cf8 0%, #6366f1 100%);
            box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
            transform: scale(1.02);
        }

        .btn-assistant {
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(14, 165, 233, 0.3);
        }

        .btn-assistant:hover {
            background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
            box-shadow: 0 6px 20px rgba(14, 165, 233, 0.4);
            transform: scale(1.02);
        }

        footer {
            font-size: 0.8rem;
            color: rgba(255, 255, 255, 0.2);
            font-weight: 300;
            border-top: 1px solid rgba(255, 255, 255, 0.03);
            padding-top: 2rem;
            width: 100%;
            max-width: 600px;
            margin: 0 auto;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Auto-Teleflow Portal Gateway</h1>
            <p class="subtitle">Satu pintu gerbang terpadu untuk mengelola dan memonitor ekosistem bot Telegram Anda.</p>
        </header>

        <div class="cards-grid">
            <!-- Card Campaigns -->
            <div class="card card-campaigns">
                <div>
                    <div class="icon">📢</div>
                    <h2>Campaigns Panel</h2>
                    <span class="card-tag">Promo Scheduler</span>
                    <p>Kelola pengiriman wave promosi otomatis ke berbagai grup target, pantau status kesehatan grup, log aktivitas, dan cadangan database terenkripsi.</p>
                </div>
                <a href="/select-panel/campaigns" class="btn btn-campaigns">Buka Campaigns Bot</a>
            </div>

            <!-- Card Assistant -->
            <div class="card card-assistant">
                <div>
                    <div class="icon">🤖</div>
                    <h2>Assistant Panel</h2>
                    <span class="card-tag">AI Sales Agent (Otan)</span>
                    <p>Kelola asisten penjualan pintar Anda yang ditenagai oleh Gemini AI. Atur katalog produk, variasi paket, FAQ produk, persona chat, dan analisis leads.</p>
                </div>
                <a href="/select-panel/assistant" class="btn btn-assistant">Buka Assistant Bot</a>
            </div>
        </div>

        <footer>
            Auto-Teleflow Bot Ecosystem &copy; 2026. All rights reserved.
        </footer>
    </div>
</body>
</html>
"""

async def proxy_request(request: Request, target_url: str):
    """Utility to proxy the HTTP request to the selected sub-app."""
    # 1. Prepare query params
    query = str(request.query_params)
    url = f"{target_url}?{query}" if query else target_url
    
    # 2. Extract request headers, removing Host & Content-Length to let httpx recalculate them
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    
    # 3. Read body
    body = await request.body()
    
    try:
        # Build proxy request
        req = client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=body
        )
        
        # Send streaming response
        res = await client.send(req, stream=True)
        
        # Prepare response headers to forward (exclude hop-by-hop headers)
        res_headers = {}
        for k, v in res.headers.items():
            if k.lower() not in ("content-length", "transfer-encoding", "content-encoding"):
                res_headers[k] = v
                
        # Check if content type is HTML to inject the floating gateway button
        content_type = res.headers.get("content-type", "").lower()
        if "text/html" in content_type:
            try:
                body_content = await res.aread()
                html_str = body_content.decode("utf-8", errors="replace")
                
                # Floating button HTML structure with sleek modern design
                floating_btn = """
                <!-- Floating Switch Bot Panel Button -->
                <div id="portal-floating-button" style="position: fixed; bottom: 25px; right: 25px; z-index: 999999;">
                    <a href="/portal" style="
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        width: 54px;
                        height: 54px;
                        border-radius: 50%;
                        background: linear-gradient(135deg, #6366f1 0%, #0ea5e9 100%);
                        color: white;
                        text-decoration: none;
                        box-shadow: 0 8px 32px 0 rgba(99, 102, 241, 0.4);
                        border: 1px solid rgba(255, 255, 255, 0.15);
                        backdrop-filter: blur(4px);
                        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                        font-size: 24px;
                        cursor: pointer;
                    " 
                    onmouseover="this.style.transform='scale(1.1) rotate(15deg)'; this.style.boxShadow='0 12px 40px 0 rgba(99, 102, 241, 0.6)';" 
                    onmouseout="this.style.transform='scale(1) rotate(0deg)'; this.style.boxShadow='0 8px 32px 0 rgba(99, 102, 241, 0.4)';"
                    title="Menu Portal Gateway">
                        ⚙️
                    </a>
                </div>
                """
                if "</body>" in html_str:
                    html_str = html_str.replace("</body>", f"{floating_btn}</body>")
                else:
                    html_str += floating_btn
                
                # Close the HTTPX response since we consumed it
                await res.aclose()
                
                return HTMLResponse(
                    content=html_str,
                    status_code=res.status_code,
                    headers=res_headers
                )
            except Exception as e:
                logger.warning(f"Failed to inject floating portal button: {e}")
                
        return StreamingResponse(
            res.aiter_bytes(),
            status_code=res.status_code,
            headers=res_headers,
            background=BackgroundTask(res.aclose)
        )
    except Exception as e:
        logger.error(f"Proxy failed for target {url}: {e}")
        return HTMLResponse(
            status_code=502,
            content=f"""
            <html>
                <body style="font-family: sans-serif; background: #0f172a; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh;">
                    <h2>502 Bad Gateway</h2>
                    <p>Gagal menghubungi server internal panel ({e}). Pastikan sub-aplikasi berjalan di latar belakang.</p>
                    <a href="/portal" style="color: #38bdf8; margin-top: 1rem; text-decoration: none;">&larr; Kembali ke Portal Gateway</a>
                </body>
            </html>
            """
        )

# Routes

@app.get("/portal", response_class=HTMLResponse)
async def get_portal(request: Request):
    """Selection panel landing page."""
    return HTMLResponse(content=PORTAL_HTML)

@app.get("/select-panel/{panel}")
async def select_panel(panel: str, request: Request):
    """Switch active panel and redirect to root."""
    if panel in ("campaigns", "assistant"):
        request.session["active_panel"] = panel
        logger.info(f"Session panel changed to: {panel}")
        
    return RedirectResponse(url="/", status_code=303)

@app.get("/")
async def root_route(request: Request):
    """Routes domain root. Shows portal if none is selected, otherwise proxies to sub-app root."""
    active_panel = request.session.get("active_panel")
    if not active_panel:
        return RedirectResponse(url="/portal", status_code=303)
        
    target_base = CAMPAIGNS_URL if active_panel == "campaigns" else ASSISTANT_URL
    return await proxy_request(request, f"{target_base}/")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_wildcard(request: Request, path: str):
    """Catches all other routes and forwards them to the selected sub-app."""
    active_panel = request.session.get("active_panel")
    if not active_panel:
        return RedirectResponse(url="/portal", status_code=303)
        
    target_base = CAMPAIGNS_URL if active_panel == "campaigns" else ASSISTANT_URL
    return await proxy_request(request, f"{target_base}/{path}")

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Portal Gateway on {PORTAL_HOST}:{PORTAL_PORT}...")
    uvicorn.run(app, host=PORTAL_HOST, port=PORTAL_PORT)
