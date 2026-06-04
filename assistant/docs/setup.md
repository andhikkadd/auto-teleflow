# Assistant Application Setup Guide

This document describes how to set up, configure, and deploy the customer inquiry assistant application (`assistant`).

---

## 1. Prerequisites
- **Python 3.9+** and `pip3` installed.
- **Telegram Bot Token** generated from `@BotFather`.
- A Telegram Account ID (use a bot like `@userinfobot` to find your ID) for `ADMIN_TELEGRAM_ID`.

---

## 2. Configuration (`.env`)
Create a `.env` file inside the `assistant/` directory based on the `.env.example` file:

```env
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
ADMIN_TELEGRAM_ID=987654321
DATABASE_PATH=data/bot.db

# Web Administration Portal
ENABLE_WEB_PANEL=true
WEB_HOST=127.0.0.1
WEB_PORT=8001
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=your_secure_password_here
WEB_SESSION_SECRET=your_32_character_hex_session_key_here

# Business Metadata Info
BUSINESS_NAME=Otan Premium Apps
WA_LINK=https://wa.me/628123456789
CHANNEL_LINK=https://t.me/OtanAppsChannel
AUTOORDER_BOT_USERNAME=OtanAutoOrderBot
AUTOORDER_BOT_LINK=https://t.me/OtanAutoOrderBot
```

---

## 3. Running Locally
Navigate into the `assistant/` folder, install requirements, and execute the launcher:
```bash
cd assistant/
pip install -r requirements.txt
python main.py
```
By default, this will boot the aiogram long-polling loop and start the FastAPI web dashboard at `http://127.0.0.1:8001`.

---

## 4. Production Deployment with PM2 (Pterodactyl Panel)
If you deploy to a production Linux VPS behind a reverse proxy (e.g., Cloudflare Tunnel/Nginx):
```bash
pm2 start main.py --name "teleflow-assistant" --interpreter python3
```
Ensure that `assistant/.env` is kept secure and not tracked by Git.
