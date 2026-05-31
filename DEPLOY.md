# Production Deployment Guide - Auto-Teleflow

This guide outlines deployment procedures for virtual private servers (VPS) and control panels (like Pterodactyl PM2).

---

## 1. Directory Structure Prep
Ensure your remote repository or code folder on the server is cloned to:
`/home/container/auto-teleflow`

### VPS Migration Checklist (If upgrading from old structure):
Move your runtime state assets into the `campaigns/` folder:
- Move `.env` $\rightarrow$ `campaigns/.env`
- Move `sessions/` $\rightarrow$ `campaigns/sessions/`
- Move `data/bot.db` $\rightarrow$ `campaigns/data/bot.db`
- Move `backups/` $\rightarrow$ `campaigns/backups/`

---

## 2. Deployment Commands

### Option A: Direct Deployment (Campaigns App Only)
To launch only the Telethon scheduler and FastAPI dashboard (the original setup):
```bash
cd /home/container/auto-teleflow/campaigns
pip3 install -r requirements.txt
python3 main.py
```

### Option B: Monorepo Deployment (Runner Orchestration)
To launch the entire suite (orchestrating campaigns and future sub-apps in a single process stream):
```bash
cd /home/container/auto-teleflow
pip3 install -r requirements.txt # Optional: install both apps' packages
python3 runner.py
```

---

## 3. Running with PM2 (Background Daemon)
To keep the application running 24/7 in the background on Linux VPS:

### Running the Monorepo Launcher:
```bash
pm2 start runner.py --name "auto-teleflow" --interpreter python3
```

### Running only the Campaigns App:
```bash
pm2 start campaigns/main.py --name "teleflow-campaigns" --interpreter python3
```
