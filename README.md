# Auto-Teleflow Bot Ecosystem

A unified Telegram automation suite combining a **Promotion Userbot (Campaigns)** and an **AI Pre-Sales Chatbot (Assistant)** managed through a single Web Portal Gateway.

> [!NOTE]
> This project is currently under active development. The AI-powered Assistant bot, in particular, is undergoing active testing and persona tuning.

---

## 📂 Project Structure

```text
auto-teleflow/
├── campaigns/       # Telegram promo broadcasting & target group scheduler
├── assistant/       # Customer support & pre-sales chatbot powered by Gemini AI
├── portal.py        # Single Web Portal Gateway
└── runner.py        # Multi-process orchestrator script
```

### 1. Campaigns (`campaigns/`)
A Telethon-based userbot designed to automatically broadcast promotional waves to target groups on a schedule, monitor group diagnostics, and output system status logs.

### 2. Assistant (`assistant/`)
An official Telegram bot built with `aiogram` v3 that uses Gemini AI to answer customer inquiries, display interactive product catalogs/pricing packages, collect leads, and redirect customers to WhatsApp.

---

## 🚀 Getting Started

1. **Configure Environment Variables**:
   Copy `.env.example` to `.env` in both `campaigns/` and `assistant/` folders, then configure the required parameters (such as API keys, bot tokens, etc.).

2. **Launch All Services**:
   Start the orchestrator in the root directory to boot the campaigns bot, assistant bot, and the unified portal concurrently:
   ```bash
   python runner.py
   ```

3. **Access the Web Panels**:
   Open your web browser and navigate to the portal gateway port (default: `http://localhost:4765` or your VPS allocated port). This landing page lets you switch between the Campaigns and Assistant dashboards. To return to the gateway page at any time, visit `http://localhost:4765/portal`.

---

## 🔒 Security & Auto-Backups

* **Secret Isolation**: All `.env` configuration files, SQLite databases (`.db`), and Telegram session files (`.session`) are ignored via `.gitignore` to prevent accidental credential exposure to public repositories.
* **Automated 2-Day Backups**: The system runs a background scheduler that automatically creates a secure, GPG-encrypted backup of database and session files every 2 days. The backup is sent directly to your configured Telegram reporting target (channel or admin account), and local backup files are cleaned up immediately to save server storage.