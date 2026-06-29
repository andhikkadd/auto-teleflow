# Telegram Userbot Framework

A resilient, modular, and fully documented Telegram userbot framework built on **Telethon**. It is designed to run 24/7 on any server/VPS using a process manager like **PM2** or **systemd** to automate message wave distributions and monitor target group health.

> [!WARNING]
> This is a **Telegram Userbot** running on a standard Telegram user account (not a BotFather bot token). Do NOT share your `.session` files in the `sessions/` directory or your `.env` credentials with anyone, and never push them to public Git repositories!

---

## Key Features

- **Strict Master Authorization**: Restricts bot command processing to authorized user IDs (`MASTER_ID`) or usernames (`MASTER_USERNAME`).
- **Concurrent Web Control Panel**: A built-in dark-themed **FastAPI + Jinja2** admin dashboard running in the same event loop for managing settings, targets, logs, templates, and backups.
- **Group Health & Validation**: Monitors target groups, tracking error states such as `FLOOD_WAIT` cooldowns, `MUTED` channels, and `NO_PERMISSION` blocks. Automates skipping of broken channels after 3 consecutive failures.
- **Automated Async Scheduler**: Automatically dispatches promo messages ("waves") at randomized delay intervals (e.g., 60-180 minutes) with safe rate-limiting delays between individual groups.
- **GPG AES256 Encrypted Backups**: Compresses codebase, SQLite databases, and Telethon session files, encrypts them securely using GPG, forwards the package to your personal Telegram chat, and purges temporary files from disk.
- **Server Health Metrics**: Monitors CPU load, RAM usage, disk space, and application uptime directly from Telegram commands or the web panel.

---

## Directory Structure

```text
.
├── main.py                    # Application entrypoint
├── config.py                  # Environment variables parser & validator
├── database.py                # Async SQLite wrapper & DB migrations
├── telegram_client.py         # Telethon client bootstrapper & OTP handler
├── commands.py                # Telegram admin commands implementation
├── scheduler.py               # Background scheduler loop for waves
├── web_panel.py               # FastAPI admin web panel application
├── server_status.py           # System resource diagnostics module
├── utils.py                   # Log sanitization and global state trackers
├── requirements.txt           # Python external dependencies
├── CHANGELOG.md               # Version history and releases log
├── DEPLOYMENT.md              # Production deployment guides
├── GITHUB_WORKFLOW.md         # Git and deployment updates workflow
├── BACKUP_RESTORE.md          # Backup and database restore guide
├── SECURITY.md                # General security checklists
├── .env.example               # Secret configuration environment template
├── .gitignore                 # Git repository exclusion file
├── data/                      # Persistent SQLite database directory (ignored by Git)
├── sessions/                  # Telethon session file storage (ignored by Git)
├── backups/                   # Temporary directory for zip/gpg backups (ignored by Git)
├── services/                  # Business logic services layer
│   ├── backup_service.py      # GPG zip backups manager
│   ├── group_service.py       # Group resolution, health & diagnostic logic
│   ├── settings_service.py    # Persisted key-value settings manager
│   ├── template_service.py    # Message template validations
│   └── wave_service.py        # Promotional wave sender orchestration
├── static/                    # Stylesheets and visual assets
├── templates/                 # Jinja2 HTML layout templates
└── docs/                      # In-depth technical guides
    ├── commands.md            # Detailed admin command usages
    ├── architecture.md        # System architecture and flow diagrams
    ├── security.md            # Security policy and GPG details
    ├── web_panel.md           # Web panel access and tunnel setups
    └── troubleshooting.md     # Error codes and resolution guides
```

---

## Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/andhikkadd/telethon.git
cd your-repo/
```

### 2. Install Dependencies
```bash
pip3 install -r requirements.txt
```

### 3. Setup Configuration
Copy the template configuration file and configure your API credentials:
```bash
cp .env.example .env
nano .env
```

### 4. Bootstrapping (First-Time Login)
Run the application interactively once to complete the Telegram authentication process:
```bash
python3 main.py
```
- Enter your phone number in international format (e.g., `+62xxxx`).
- Input the OTP code sent to your Telegram account.
- Input your Two-Step Verification (2FA) password if enabled.
- Once logged in, terminate the script using `Ctrl + C`. Your session files are now securely saved in `sessions/`.

### 5. Start Background Daemon via PM2
```bash
pm2 start main.py --name "promo-userbot" --interpreter python3
```

---

## Documentation

For advanced features and setup guidelines, refer to the following documents:
- [Deployment Guide](DEPLOYMENT.md) - Standard server deployment, systemd services, and startup triggers.
- [Git & GitHub Workflow](GITHUB_WORKFLOW.md) - Best practices for pushing updates and pulling them onto production servers.
- [Backup Recovery Guide](BACKUP_RESTORE.md) - Restoring system sessions and SQLite state from GPG backups.
- [Web Control Panel Guide](docs/web_panel.md) - Detailed guide on accessing the panel and setting up Cloudflare Tunnels.
- [Admin Commands Reference](docs/commands.md) - Complete dictionary of Telegram chatbot admin commands.
- [Security Policies](docs/security.md) - Security guidelines and environment protections.
- [Troubleshooting](docs/troubleshooting.md) - Resolving common issues like FloodWait, database locked, and dependency issues.
