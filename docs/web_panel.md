# Web Control Panel Guide

This project includes a built-in Web Control Panel built on **FastAPI** and **Jinja2** templates. The server runs in the same process event loop as the Telegram Userbot. The panel enables you to monitor the bot's runtime status, view server resource utilization charts, manage targets/templates, inspect logs, run diagnostic cleaning, and trigger encrypted GPG backups visually.

---

## 1. Environment Configurations (.env)

Ensure the following variables are configured in your `.env` file before booting the application:

```env
# Enable or disable the web control panel (true/false)
ENABLE_WEB_PANEL=true

# Host binding (set to 0.0.0.0 to listen on all interfaces)
WEB_HOST=0.0.0.0

# Network port for FastAPI / Uvicorn
WEB_PORT=8000

# Administrator Credentials
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=your_strong_admin_password

# Secret key for cookie session signatures
WEB_SESSION_SECRET=your_random_32_character_hexadecimal_string
```

> [!WARNING]
> Never leave `WEB_ADMIN_PASSWORD` or `WEB_SESSION_SECRET` empty when `ENABLE_WEB_PANEL=true`. The system will validate credentials on startup and fail immediately if default or insecure configurations are detected.

---

## 2. Network Ports & Firewall Settings

To access the Web Panel directly using your server's public IP address:

1. Confirm that the network port configured in `WEB_PORT` (default `8000`) is allowed through your server's firewall (e.g. **UFW** on Ubuntu/Debian):
   ```bash
   sudo ufw allow 8000/tcp
   ```
2. If utilizing cloud hosting instances (such as AWS EC2, Google Cloud Platform, or DigitalOcean Droplets), update your network security rules (**Security Groups / Inbound Rules**) to allow TCP traffic on port `8000` from your IP.
3. Access the dashboard in your web browser: `http://<YOUR_SERVER_IP>:8000`.

---

## 3. Secure Deployment via Cloudflare Tunnel (Recommended)

If your server operates behind a NAT network, does not have a static public IP, or firewall policies prevent exposing ports, you can deploy a secure **Cloudflare Tunnel** (free of charge) to expose the panel without open ports:

### Step A: Initialize the Tunnel in Cloudflare Dashboard
1. Log in to your Cloudflare Dashboard and navigate to **Zero Trust** > **Networks** > **Tunnels**.
2. Click **Create a Tunnel**, choose a name (e.g. `telegram-userbot`), and click **Save**.
3. Cloudflare will display installation scripts and provide a unique **Tunnel Token** (a long alphanumeric string).

### Step B: Install and Run Cloudflared on your VPS
1. Download and install the `cloudflared` binary on your server:
   ```bash
   curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared.deb
   ```
2. Run the tunnel service in the background using PM2:
   ```bash
   pm2 start cloudflared --name "cf-tunnel" -- tunnel run --token <YOUR_CLOUDFLARE_TUNNEL_TOKEN>
   ```
3. In the Cloudflare Zero Trust Dashboard, under the **Public Hostname** tab for your tunnel, add an entry:
   - **Subdomain/Domain**: `userbot.yourdomain.com`
   - **Service Type**: `HTTP`
   - **URL**: `localhost:8000` (adjust port to match your `WEB_PORT`).
4. Click **Save Hostname**. The web panel is now securely accessible via `https://userbot.yourdomain.com` with automated SSL certificate provisioning.

---

## 4. Emergency Telegram Chat Controls

While the Web Panel offers a visual interface for daily management, the **Telegram Admin Chat Commands** run in parallel as an emergency control mechanism.

If the Web Panel is inaccessible due to firewall blocks, proxy updates, or during the initial OTP authentication phase:
- Dispatch administrative commands like `!status`, `!pause`, `!resume`, `!health`, or `!backup` directly from your authorized Master account in the Telegram application.
- State changes made via Telegram commands (such as suspending the scheduler with `!pause`) will synchronize instantly and update the Web Control Panel dashboard in real-time.
