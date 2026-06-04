# Telegram Assistant Bot Command & Inquiry Guides

This document explains the bot commands and conversational features available to users.

---

## 1. Bot Commands

The following slash commands are registered and processed by Otan:

### `/start`
- **Description**: Displays the welcome greeting card and menu interface.
- **Buttons Included**:
  - `📁 Katalog Produk`: Displays the catalog.
  - `📝 Cara Beli`: Displays the buying instructions.
  - `💳 Payment`: Displays the payment methods.
  - `🛡️ Garansi`: Displays the warranty procedure.
  - `💬 Chat Admin WA`: Direct URL link to WhatsApp.

### `/katalog`
- **Description**: Fetches all active products from the SQLite database catalog, formatted as category groupings.

### `/help`
- **Description**: Explains how users can ask Otan queries (e.g. typing names of apps like `canva` or `netflix`).

---

## 2. Conversational Intent Processing
Users can chat freely in natural language. Otan cleans the queries and matches them:

1. **Keyword Match (FAQ Intents)**:
   - Matches keywords like `cara beli`, `bayar`, `rekening`, `klaim`, `komplain` to their respective FAQ cards.
2. **Product & Alias Match (Fuzzy Matching)**:
   - Matches app queries like `canfva`, `canvaa`, or `netflik` to `Canva Pro` or `Netflix Premium` using `rapidfuzz` string comparison with typo-correction.
3. **Fallback Handoff**:
   - If no product or FAQ template matches, Otan replies politely and offers a direct click-to-chat button with support staff on WhatsApp.
