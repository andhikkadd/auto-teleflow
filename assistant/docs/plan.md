# Implementation Plan - AI-Powered Sales Assistant

This plan outlines the design and step-by-step development required to upgrade the `assistant/` application into a fully AI-assisted sales agent (Otan) using Google AI Studio's Gemini API (`google-genai` SDK).

## 1. Database Schema Enhancements
We will update `database.py` with the following changes:
- **`products` table**:
  - Add `sales_note`, `requirement_note`, `process_note`, `warranty_note`, and `restriction_note` columns.
  - Implement automatic `ALTER TABLE` statements for backward compatibility with existing databases.
- **`product_packages` table**:
  - Create the new `product_packages` table.
  - If a legacy `product_variants` table exists and has rows, automatically migrate all its rows into `product_packages` on initialization.
- **`product_faqs` table**:
  - Create table with columns: `id`, `product_id`, `question`, `keywords`, `answer`, `is_active`, `created_at`, `updated_at`.
- **`conversation_state` table**:
  - Create table to store current session context: `telegram_user_id` (PK), `last_product_id`, `last_intent`, `last_topic`, `updated_at`.
- **`leads` table**:
  - Add `lead_score` (default 0) column to track hot leads.
- **`ai_usage` table**:
  - Track daily calls: `id`, `telegram_user_id`, `provider`, `model`, `status`, `error_message`, `created_at`.
- **`ai_cache` table**:
  - Cache responses to prevent API quota waste: `id`, `normalized_message`, `context_hash`, `reply_text`, `intent`, `product_id`, `created_at`, `expires_at`.

## 2. Global & AI Configurations
We will define key-value entries in the `settings` table to control persona and AI features. This avoids forcing values in `.env` and allows admins to change everything dynamically in the web panel:
- `ai_enabled` (1/0)
- `gemini_api_key` (masked in UI, loaded securely, falling back to `.env`)
- `gemini_model` (e.g. `gemini-2.5-flash`)
- `ai_temperature` (float)
- `ai_style_strength` (low/medium/high)
- `ai_timeout_seconds` (integer)
- `ai_max_calls_per_user_per_day` (integer)
- `ai_daily_global_limit` (integer)
- **Persona Configs**:
  - `bot_display_name` (default: Otan)
  - `bot_role_desc` (role prompt)
  - `bot_tone_style` (friendly, professional, etc.)
  - `bot_emoji_level` (low/medium/high)
  - `bot_humor_level` (low/medium/high)
  - `bot_reply_length` (short/medium/long)
  - `out_of_scope_mode` (reject/redirect)
  - `price_answer_mode` (exact_only/allow_estimated)

## 3. Web Panel Pages
We will build/enhance HTML templates and routes:
1. **Products Catalog (`products.html` / `web_panel.py`)**:
   - Update fields to include Sales, Requirement, Process, Warranty, and Restriction Notes.
2. **Packages Management (`packages.html`)**:
   - New page to add, edit, toggle, and delete packages/pricelist for active products.
3. **Product FAQ (`product_faq.html`)**:
   - New page to add, edit, and delete questions/keywords/answers mapped per product.
4. **Persona Settings (`persona.html`)**:
   - Form to customize Otan's personality, tone, humor level, and style strength.
5. **AI Settings (`ai_settings.html`)**:
   - Form to configure API limits, mask and save Gemini API key, view errors, and test prompt generation.
6. **Leads (`leads.html`)**:
   - View conversation history, matched products/intents, and lead scores.

## 4. Gemini Integration & Prompt Engine
We will create a new service `services/ai_service.py` to handle the interaction with Gemini.
- Uses `google-genai` SDK: `client = genai.Client(api_key=api_key)`
- Dynamically build the prompt with:
  - Otan's persona settings.
  - Strict database facts context (Product info, matched packages, aliases, FAQs, global links).
  - Conversation history.
  - Query content.
- Enforces strict JSON output schema:
  ```json
  {
    "intent": "WARRANTY",
    "confidence": 95,
    "product_id": 1,
    "reply_text": "Iya kak, Canva 1 bulan garansi full...",
    "show_wa_button": true,
    "show_autoorder_button": false,
    "lead_score": 80
  }
  ```
- Strict validation:
  - If AI invents prices or claims payment is validated, drop the response and fall back to database rule templates.
  - Handle exceptions gracefully with a friendly Indonesian redirection to WhatsApp support.

## 5. Bot Conversation Pipeline
We will update `bot.py` and `services/reply_service.py`:
- Normalize incoming messages.
- Fetch conversation state.
- Match product and intent using database facts.
- Evaluate AI limits (daily user & global usage).
- If AI matches: call `ai_service.py` and check cache.
- Else: use database rule-based reply.
- Format replies with action buttons and log the lead.
