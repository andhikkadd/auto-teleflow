# Troubleshooting Guide

This document lists common issues you might encounter while running the Telegram Userbot Promo Framework along with their solutions.

---

## 1. Installation & Bootstrapping Failures

### `ModuleNotFoundError: No module named 'telethon'`
* **Cause**: Python dependencies have not been installed in your runtime environment.
* **Solution**:
  Run the installation command in your terminal/virtual environment:
  ```bash
  pip install -r requirements.txt
  ```
  If using PM2 on your server, verify that the active process interpreter points to the correct virtual environment folder containing these dependencies.

### `ValueError: API_ID is required but missing in .env`
* **Cause**: The `.env` configuration file is missing, or the `API_ID` and `API_HASH` fields have not been filled in.
* **Solution**:
  1. Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
  2. Edit `.env` using a terminal text editor (like nano) and insert your Telegram API credentials obtained from [https://my.telegram.org](https://my.telegram.org).

---

## 2. Authentication & Rate-Limiting Issues

### Account Logged Out / Invalid Session
* **Cause**: The active MTProto session was terminated from your Telegram devices menu, or the session binary files under `sessions/` were corrupted or deleted.
* **Solution**:
  1. Stop the bot daemon process:
     ```bash
     pm2 stop promo-userbot
     ```
  2. Purge the invalid session files:
     ```bash
     rm sessions/promo_userbot.session*
     ```
  3. Start the application interactively in your terminal to complete a new OTP authentication:
     ```bash
     python main.py
     ```
  4. Once logged in, stop the interactive process using `Ctrl + C` and restart the daemon via PM2.

### `FloodWaitError` / Temporary Telegram Limitations
* **Cause**: Telegram rate-limited your account because messages or logins were sent too rapidly.
* **Solution**:
  - If the rate limit is hit during wave dispatches, the framework automatically handles the wait dynamically (if the wait time is < 90 seconds) or auto-skips the group to avoid blocks.
  - If hit during bootstrapping/login, you must wait the exact duration specified in the console logs (in seconds) before trying again.
  - **Prevention**: Do not set `DELAY_BETWEEN_GROUPS_SECONDS` too low. A safe interval is 15-30 seconds between groups.

---

## 3. Database Constraints

### `sqlite3.OperationalError: database is locked`
* **Cause**: The SQLite database engine is locked due to concurrent write processes or a previously unclosed connection from a crash.
* **Solution**:
  - Verify that multiple instances of the python script are not running concurrently on the server:
     ```bash
     ps aux | grep python
     ```
     Terminate any orphaned processes using `kill <PID>`.
  - Restart the application via PM2. Database connection timeouts are set to 30.0s to mitigate locks.

---

## 4. Entity Resolution Failures

### `ValueError: Could not find the input entity for...`
* **Cause**: The userbot was unable to locate the target group. This occurs if you supplied an invalid username, if the group is private and the account is not a member, or if the account has been banned from the target.
* **Solution**:
  - Check the target group username or link format (e.g., `@group_username` or public links like `t.me/group_username`).
  - Open the group link in a standard Telegram client using your userbot account to confirm membership status and active write permissions.

---

## 5. Encryption & Backup Failures

### `RuntimeError: GPG is not available and ALLOW_UNENCRYPTED_BACKUP=false`
* **Cause**: A backup was requested, but GnuPG (`gpg`) is not installed on the system, and security settings prohibit sending unencrypted archives.
* **Solution**:
  - **Option A (Recommended)**: Install GnuPG on your server system:
     ```bash
     # Debian/Ubuntu
     sudo apt-get update && sudo apt-get install -y gnupg
     ```
  - **Option B**: If you are in a constrained shared environment where installing packages is not possible, enable unencrypted fallbacks in your `.env`:
     ```env
     ALLOW_UNENCRYPTED_BACKUP=true
     ```
