# Userbot Admin Commands Reference

This page provides a comprehensive guide to all admin commands available within the Telegram Userbot Promo Framework. All commands must be prefixed with `!`.

> [!IMPORTANT]
> The commands below can only be executed by the authorized master account defined in `.env` (via `MASTER_ID` or `MASTER_USERNAME`). Messages from unauthorized users are silently dropped.

---

## Command Dictionary

### 1. System Control & Diagnostics

#### `!help` / `!menu`
Displays the help menu listing all available commands and their usage formats.

#### `!ping`
Verifies if the userbot process is active and responsive.
* **Response**: `🏓 Pong! Bot is active and running.`

#### `!status`
Displays runtime configuration metrics of the userbot.
* **Fields Displayed**:
  - Scheduler Status (`RUNNING` or `PAUSED`)
  - Timestamp of the last wave execution
  - Estimated timestamp of the next wave execution
  - Active wave delay ranges (minimum/maximum minutes)
  - Number of target groups (Active vs Skipped)
  - Total number of active message templates in the database

#### `!server`
Displays hosting server metrics.
* **Fields Displayed**:
  - Operating system details and kernel version
  - Python runtime version
  - Userbot process uptime
  - System host uptime
  - CPU utilization bar (%)
  - RAM utilization bar (%) with active and total space
  - Disk space utilization bar (%) with active and total capacity

#### `!reload`
Reloads configurations from the `.env` file and updates the in-memory state with database settings. Use this command after manually modifying environment variables or database tables.

---

### 2. Wave Scheduling & Dispatch

#### `!pause`
Pauses the automatic wave scheduler.
* **Behavior**: The background scheduler is suspended, but Telegram command handlers remain active 24/7. The paused state is saved to the database.

#### `!resume`
Resumes the automatic wave scheduler.
* **Behavior**: The scheduler calculates a new randomized delay interval and schedules the next wave. The paused state is set to `0` in the database.

#### `!wave`
Immediately triggers a manual wave execution across all active target groups.
* **Safety Lock**: Enforces a concurrency lock using `state.active_wave_task` to prevent simultaneous wave dispatches.

#### `!setdelay <min_minutes> <max_minutes>`
Modifies the randomized delay boundaries directly from Telegram chat.
* **Example**: `!setdelay 30 120` (sets randomized intervals between 30 and 120 minutes).
* **Behavior**: Updates settings in the database and applies them to the next scheduler cycle.

#### `!logs`
Displays execution logs for the most recent wave.
* **Behavior**: Outputs Wave ID, started time, elapsed duration, success/fail counts, and the specific delivery status of each group target.

---

### 3. Target Group Management

#### `!groups`
Lists all registered target groups in the database with their database ID (DB ID) and status (`[✅ ACTIVE]` or `[❌ SKIPPED]`).

#### `!addgroup <username_or_link>`
Registers a new group target in the database.
* **Formats Supported**:
  - Username: `@group_username` or `group_username`
  - Public link: `https://t.me/group_username`
* **Behavior**: Resolves the Telegram entity online. If found, retrieves the title, username, and raw input, then saves them to the database (marked ACTIVE by default).
* **Errors**: If the group is private or the userbot lacks permissions to access/join it, the command displays a detailed resolution error.

#### `!delgroup <DB_ID_or_username>`
Permanently deletes a group target from the database.
* **Example**: `!delgroup 3` or `!delgroup @group_test`

#### `!skip <DB_ID_or_username>`
Temporarily skips a group target during wave dispatches without deleting it.
* **Example**: `!skip 2` or `!skip @group_test`
* **Behavior**: Sets `is_skipped` to `1`. The group will be ignored in both automatic and manual waves.

#### `!unskip <DB_ID_or_username>`
Re-enables a skipped group target.
* **Example**: `!unskip 2`

---

### 4. Template & Test Management

#### `!templates`
Lists all promotional message templates saved in the database, showing their ID, status, and a text preview.

#### `!addtemplate <message_body>`
Adds a new promotional message template to the database. Supports newlines, emojis, and standard Telegram markdown styling.
* **Example**:
  ```text
  !addtemplate Weekend Special Offer! 🚀
  Enjoy 50% off all packages.
  DM @admin for details!
  ```

#### `!deltemplate <template_id>`
Permanently deletes a template from the database using its ID.
* **Example**: `!deltemplate 2`

#### `!preview`
Randomly selects an active template from the database and sends it to the admin chat as a layout check.

#### `!test <DB_ID_or_username> [custom_message]`
Dispatches a test message immediately to a single target group to verify write permissions.
* **Behavior**: If `[custom_message]` is omitted, the bot selects an active template randomly.
* **Example**: `!test 5 Hello, this is a test` or `!test @group_test`

---

### 5. Database & Security Backups

#### `!backup`
Immediately triggers an encrypted system backup.
* **Behavior**:
  1. Gathers all python source files, databases (`data/bot.db`), active session files (`sessions/`), and guides into a ZIP archive.
  2. Encrypts the ZIP archive with GPG using **AES256** symmetric encryption and the `BACKUP_PASSWORD` from `.env`.
  3. Sends the encrypted `.gpg` file to your configured `BACKUP_TARGET` channel.
  4. Deletes the temporary unencrypted ZIP and GPG files from the disk.
* **Fallback**: If GPG is not available, the bot falls back to an unencrypted `.zip` archive only if `ALLOW_UNENCRYPTED_BACKUP` is set to `true` in `.env`. Otherwise, the backup fails for security reasons.
