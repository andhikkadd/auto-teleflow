# Auto-Teleflow

A modular Telegram automation suite and monorepo designed to manage marketing distribution tasks and customer support automations concurrently.

---

## Workspace Structure

The workspace is organized as a monorepo containing two distinct sub-applications:

```text
auto-teleflow/
├── campaigns/       # Existing Telegram promo/wave scheduler (Telethon userbot)
├── assistant/       # Planned BotFather customer support chatbot (Placeholder)
├── runner.py        # Central monorepo orchestrator launcher
├── DEPLOY.md        # Deployment instructions for production servers
└── SECURITY.md      # Global security checklists
```

### 1. Campaigns (`campaigns/`)
The campaign application is a Telethon-based userbot designed for automated promotional wave scheduling, target channel diagnostic monitoring, and system metrics reporting. It features a built-in dark-themed **FastAPI + Jinja2** administration panel.

### 2. Assistant (`assistant/`)
The assistant application is a planned official Telegram Bot (built on `aiogram`) to act as a pre-sales responder. It will answer product questions and route customers to human representatives on WhatsApp.

---

## Quick Start & Running Locally

### Direct Execution (Campaigns only)
Navigate directly to the campaigns directory to configure and run:
```bash
cd campaigns/
pip install -r requirements.txt
cp .env.example .env
# Configure variables in .env
python main.py
```

### Centralized Orchestration (Monorepo Launcher)
To run the entire suite under a single unified console stream:
```bash
python runner.py
```
This starts the `campaigns` sub-application in a subprocess, automatically prefixing output streams with `[campaigns]`. Once the `assistant` app is implemented, it will run concurrently in the same orchestrator.
