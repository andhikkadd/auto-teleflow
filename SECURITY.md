# Security Policy

We take the security of the **Auto-Teleflow** suite very seriously. This document outlines the security architecture, best practices, and checklists for both the campaigns and assistant applications.

---

## 1. Core Secret Isolation
- **No Shared Environments**: The `.env` files for `campaigns` and `assistant` must remain separate.
- **Git Protection**: Never commit `.env` or session tokens/databases to version control. They are blocked by the root `.gitignore`.

---

## 2. Campaigns Security Checklist (Telethon Userbot + FastAPI)
- **Strong Credentials**: Set `WEB_ADMIN_PASSWORD` to a long, complex string.
- **Session Encryption**: Use `BACKUP_PASSWORD` to encrypt GPG backups of databases and sessions.
- **CSRF Tokens**: The web panel is protected with CSRF validation middleware. Ensure `WEB_SESSION_SECRET` is a unique 32-character key.
- **IP Rate Limiting**: Limit brute force logins (5 attempts per 10 minutes).
- **Log Sanitization**: Standard output/error is run through a regex-based logs sanitization filter to prevent leakage of the API Hash or OTP codes.

---

## 3. Assistant Security Checklist (aiogram Bot)
- **Token Protection**: Keep `TELEGRAM_BOT_TOKEN` secure.
- **User Validation**: Ensure only messages from Telegram users are processed, and restrict admin functionalities using strict chat-ID validation gates.

---

## 4. Reporting Vulnerabilities
If you discover a security vulnerability in this project, please **do not open a public issue**. Instead, report it privately to the system administrator or the repository maintainer.
