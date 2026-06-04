# Assistant Security Hardening Checklist

This document details the security layers implemented to safeguard the assistant app, databases, and admin sessions.

---

## 1. Web Portal & Session Hardening
- **Constant-Time Comparison**: Admin login credentials are validated using `hmac.compare_digest` to mitigate timing attack disclosures.
- **CSRF Protection**: All POST form submittals are checked against a cryptographically strong session token (`csrf_token`) using `hmac.compare_digest` verification.
- **Strict Password Validations**: The application crashes during bootstrap if default, blank, or weak admin passwords/session secrets are configured in `.env`.
- **HttpOnly Secure Session Cookies**: The administration session state is signed with `WEB_SESSION_SECRET` via Starlette's `SessionMiddleware`.

---

## 2. Database Hardening
- **Parameterized SQL Queries**: All SQLite interactions are structured with placeholder variables (parameterization `?`) instead of string interpolation to prevent SQL Injection (SQLi).
- **Git Shield**: SQLite files (`data/*.db`, journal records) and the local `.env` configuration files are blocked at the repository root `.gitignore` level.

---

## 3. Log Protection
- **Token Sanitization**: The application explicitly avoids logging sensitive information such as the `BOT_TOKEN`, `WEB_ADMIN_PASSWORD`, or session cookies to system logs or stdout.
- **Master User Check**: Only interactions initiated through the official Telegram client interface are registered as leads; administrative commands are guarded strictly by validation checks.
