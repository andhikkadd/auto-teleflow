# Security Policy

We take the security of our Telegram Userbot Promo Framework very seriously. This document outlines the security architecture, best practices, and reporting procedures.

For a detailed security guide and checklists, see the [Security Documentation](docs/security.md).

---

## Security Checklists

### Production Deployment Checklist
- [ ] Set `WEB_ADMIN_PASSWORD` to a strong, random password.
- [ ] Set `WEB_SESSION_SECRET` to a unique 32-character hexadecimal key.
- [ ] Set `BACKUP_PASSWORD` to a strong passphrase for GPG backups.
- [ ] Use `MASTER_ID` instead of `MASTER_USERNAME` for chat command controls.
- [ ] Set `WEB_TRUST_PROXY=true` only if deploying behind a trusted reverse proxy (like Cloudflare Tunnel or Nginx).
- [ ] Ensure `sessions/` and `.env` are listed in `.gitignore` and not tracked by Git.
- [ ] Ensure `DELETE_LOCAL_BACKUP_AFTER_SEND` is set to `true` to clean up backup files from the disk.

### Development Security Checklist
- [ ] Never share your `.session` files or session databases. They contain raw login tokens that bypass 2FA/OTP.
- [ ] Test GPG encryption using a local password before deploying automated backups.
- [ ] Check console logs to ensure no secrets or API keys are printed in clear text.

---

## Reporting Vulnerabilities

If you discover a security vulnerability in this project, please **do not open a public issue**. Instead, report it privately to the system administrator or the maintainer.

Provide details about:
1. The type of vulnerability.
2. Steps to reproduce the issue.
3. The potential impact.
