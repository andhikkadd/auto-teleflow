# Security Policy

Security is a primary design goal of the Telegram Userbot Promo Framework. Because the userbot runs on a standard Telegram user account (via MTProto sessions, rather than BotFather tokens), credential leaks can lead to complete account takeovers.

Follow this security checklist strictly in development and production environments.

---

## 1. Secrets and Session Protection

- **`.env` File**: Stores all configuration secrets including `API_ID`, `API_HASH`, `WEB_ADMIN_PASSWORD`, `WEB_SESSION_SECRET`, and `BACKUP_PASSWORD`. **NEVER** commit this file to public or private Git repositories.
- **`sessions/` Folder**: Contains `.session` and `.session-journal` SQLite files which store MTProto authorization keys. These keys are equivalent to your password and OTP. Anyone with access to these session files can access your Telegram account without needing an OTP.
- **Git Protections**: The default `.gitignore` is hard-coded to ignore `.env`, `sessions/*.session`, `sessions/*.session-journal`, `data/*.db`, and backup directories. Verify track logs with `git status` before pushing changes.

---

## 2. Web Control Panel Hardening

The FastAPI Web Control Panel incorporates several layers of defense-in-depth:

### A. Authentication Guard
- Admin route protection is enforced via a consolidated authentication middleware.
- Admin credentials (`WEB_ADMIN_USERNAME`, `WEB_ADMIN_PASSWORD`) are matched using `hmac.compare_digest` to prevent timing attacks.
- Failed logins trigger a rate limiter restricting requests to a maximum of **5 failures per 10 minutes** per IP.

### B. CSRF Protection
- A custom FastAPI middleware enforces Cross-Site Request Forgery (CSRF) validation on all state-changing `POST` forms.
- Dynamic unique tokens are injected into forms and checked using `hmac.compare_digest` against the session token.

### C. Rate Limits and Cooldowns
- Sensitive actions (`manual wave`, `backup generation`, `auto-clean`) are protected by a **30-second cooldown** to prevent double-submissions or request flooding.
- Active waves are guarded by an asynchronous lock (`state.active_wave_task`) to prevent overlapping task creations.

### D. Reverse Proxy Integration
- When deployed behind Cloudflare Tunnels, Nginx, or other reverse proxies, configure `WEB_TRUST_PROXY=true` in `.env` to parse the client's real IP from the `X-Forwarded-For` header for accurate rate-limiting.

---

## 3. Telegram Admin Authorization

Telegram chat commands (prefixed with `!`) are protected by authorization filters in `commands.py`:
1. **Master ID Check**: If `MASTER_ID` is set, only messages from that numerical Telegram user ID are processed. This is the most secure method.
2. **Master Username Check**: If `MASTER_ID` is empty, the bot checks the sender's username.
3. **Silent Drop**: Unauthorized commands are silently ignored (no response sent) to hide the bot's existence from attackers.
4. **Sanitized Exceptions**: Any exceptions or errors returned to the chat are sanitized using regex masks to prevent disclosing system paths, session strings, or passwords.

---

## 4. Encrypted Backups (.gpg)

The backup system prioritizes data confidentiality:
- **AES-256 Symmetric Encryption**: Backups are encrypted via `gpg` with a passphrase from `BACKUP_PASSWORD`.
- **Zero-leak environment backups**: Even if `BACKUP_INCLUDE_ENV` is set to `true`, the framework sanitizes the backup zip by removing the values of `BACKUP_PASSWORD`, `WEB_ADMIN_PASSWORD`, `WEB_SESSION_SECRET`, and `API_HASH`.
- **Passphrase Security**: Passphrases are piped to GPG via standard input (`stdin`) to prevent disclosure in server process lists (e.g., `ps aux`).
- **Storage Protection**: If `DELETE_LOCAL_BACKUP_AFTER_SEND` is `true`, temporary unencrypted ZIP and GPG archives are immediately unlinked from the server disk post-transmission.

---

## 5. Log Masking and Sanitization

Standard Output (`stdout`) and Standard Error (`stderr`) are sanitized in real time by the logging framework:
- Pattern scanners automatically redact `API_HASH` (32-character hex string) and common OTP codes.
- Exception traces are intercepted and sanitized before write-out to logs.
- Recommended logging level: `INFO`.
