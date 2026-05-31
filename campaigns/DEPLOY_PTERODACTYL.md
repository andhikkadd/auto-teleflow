# Deployment Guide

This guide describes how to deploy the Telegram Userbot Promo Framework to a production environment (such as a Linux VPS, cloud instance, or generic hosting container) and configure it to run continuously in the background.

---

## 1. Prerequisites

- A server running Linux (Ubuntu 20.04+, Debian, CentOS, etc.).
- Python 3.9+ and `pip3` installed.
- Telegram API Credentials (`API_ID` and `API_HASH`) obtained from [https://my.telegram.org](https://my.telegram.org).
- GnuPG (GPG) installed if you want encrypted backups (optional but highly recommended).

---

## 2. Step-by-Step Installation

### Step A: Clone the Repository
Clone the codebase to your target server:
```bash
git clone https://github.com/yourusername/your-repo-name.git /opt/telegram-userbot
cd /opt/telegram-userbot
```

### Step B: Set Up Python Virtual Environment
It is highly recommended to isolate dependencies inside a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step C: Install Dependencies
Install all required python libraries:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step D: Configure Environment Variables
Copy the `.env.example` file to `.env` and fill in your variables:
```bash
cp .env.example .env
nano .env
```
Ensure you configure:
- `API_ID` & `API_HASH` (Your Telegram credentials)
- `MASTER_USERNAME` (Your personal Telegram handle to accept commands)
- `WEB_ADMIN_PASSWORD` (A secure password for the web panel admin portal)
- `WEB_SESSION_SECRET` (A long random string to sign cookie sessions)

---

## 3. Bootstrapping (Initial Login & OTP)

Before running the application in the background, you must run it interactively once to authenticate with Telegram.

1. Execute the main program:
   ```bash
   python main.py
   ```
2. You will be prompted to enter your phone number. Format it internationally (e.g., `+628123456789`).
3. Enter the login OTP sent to your Telegram app.
4. If Two-Factor Authentication (2FA) is enabled on your account, enter your cloud password.
5. Once authenticated, the console will show `Userbot successfully logged in as...`.
6. Terminate the process by pressing `Ctrl + C`. The authentication session is now safely stored in the `sessions/` directory.

---

## 4. Running 24/7 in the Background

### Option A: Using PM2 (Recommended)
PM2 is a production process manager that keeps your application alive, automatically restarting it if it crashes:

1. Install NodeJS and PM2 globally (if not already installed):
   ```bash
   npm install -g pm2
   ```
2. Start the userbot:
   ```bash
   pm2 start main.py --name "telegram-userbot" --interpreter ./venv/bin/python
   ```
3. Set PM2 to automatically startup on server boot:
   ```bash
   pm2 startup
   pm2 save
   ```

### Option B: Using systemd
Alternatively, you can create a systemd service file:

1. Create `/etc/systemd/system/telegram-userbot.service`:
   ```ini
   [Unit]
   Description=Telegram Userbot Promo Framework
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/opt/telegram-userbot
   ExecStart=/opt/telegram-userbot/venv/bin/python main.py
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
2. Reload systemd configurations and start the service:
   ```bash
   systemctl daemon-reload
   systemctl enable telegram-userbot
   systemctl start telegram-userbot
   ```
3. View logs:
   ```bash
   journalctl -u telegram-userbot -f
   ```

---

## 5. Web Control Panel & Reverse Proxy

If `ENABLE_WEB_PANEL` is set to `true`, the FastAPI dashboard will listen on `WEB_HOST` (e.g., `0.0.0.0`) and `WEB_PORT` (e.g., `8000`).

- **Direct Access**: Open `http://<YOUR_SERVER_IP>:8000` in your web browser.
- **Port Constraints & NAT**: If your server is behind a NAT network, firewall, or you do not want to expose port 8000 directly, use a tool like **Cloudflare Tunnel** or **Nginx** as a reverse proxy to route traffic securely over HTTPS.
