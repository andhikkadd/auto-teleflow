import urllib.parse
from services.settings_service import settings_svc
from services.product_service import product_svc

class ReplyService:
    @staticmethod
    async def get_wa_link(message_text: str = None) -> str:
        base_wa = await settings_svc.get_setting("wa_link", "")
        if not base_wa:
            return "#"
        if not message_text:
            return base_wa
            
        # Append pre-filled message text safely
        encoded_text = urllib.parse.quote(message_text)
        # Check if the WA link already has query parameters
        if "?" in base_wa:
            return f"{base_wa}&text={encoded_text}"
        else:
            return f"{base_wa}?text={encoded_text}"

    @staticmethod
    async def format_reply(match_result: dict, query_text: str) -> dict:
        """
        Formats the text and buttons for a given match result.
        Returns a dict:
        {
            "text": str,
            "buttons": list of dicts [{"text": str, "url": str}]
        }
        """
        match_type = match_result["type"]
        
        # 1. Product reply formatting
        if match_type == "product":
            product = match_result["matched_object"]
            prod_name = product["name"]
            
            # Retrieve variants for pricelist
            variants = await product_svc.get_variants_for_product(product["id"])
            pricelist_str = ""
            if variants:
                pricelist_lines = []
                for v in variants:
                    formatted_price = f"Rp {v['price']:,}".replace(",", ".")
                    note_suffix = f" _({v['note']})_" if v.get('note') else ""
                    pricelist_lines.append(f"• {v['name']} - **{formatted_price}**{note_suffix}")
                pricelist_str = "\n**Pricelist:**\n" + "\n".join(pricelist_lines) + "\n\n"
            
            # Format WhatsApp prefilled message
            wa_msg = f"Mau beli {prod_name}"
            wa_url = await ReplyService.get_wa_link(wa_msg)
            
            # Check if autoorder is supported
            is_autoorder = (product["autoorder_supported"] == 1)
            
            if is_autoorder:
                # Custom links for this specific product or fallback to setting
                bot_username = product["autoorder_bot_username"] or await settings_svc.get_setting("autoorder_bot_username", "")
                bot_link = product["autoorder_bot_link"] or await settings_svc.get_setting("autoorder_bot_link", "")
                
                text = (
                    f"**{prod_name}** tersedia kak ✅\n\n"
                    f"{pricelist_str}"
                    f"Untuk pembelian manual, bisa langsung hubungi admin via WhatsApp. "
                    f"Nanti admin bantu proses ordernya.\n\n"
                    f"Kalau mau proses lebih cepat, {prod_name} juga tersedia di bot autoorder kami.\n\n"
                    f"Kirim ke admin:\n"
                    f"`Mau beli {prod_name}`"
                )
                
                buttons = [
                    {"text": "💬 Chat Admin WA", "url": wa_url},
                    {"text": "⚡ Bot Autoorder", "url": bot_link if bot_link else f"https://t.me/{bot_username}"}
                ]
            else:
                text = (
                    f"**{prod_name}** tersedia kak ✅\n\n"
                    f"{pricelist_str}"
                    f"Untuk stok, detail, dan pembelian bisa langsung hubungi admin via WhatsApp ya. "
                    f"Nanti admin bantu proses ordernya.\n\n"
                    f"Kalau mau chat admin, bisa langsung kirim:\n"
                    f"`Mau beli {prod_name}`"
                )
                
                buttons = [
                    {"text": "💬 Chat Admin WA", "url": wa_url}
                ]
                
            return {"text": text, "buttons": buttons}

        # 2. FAQ Reply formatting
        elif match_type == "faq":
            faq = match_result["matched_object"]
            intent = faq["intent"]
            text = faq["answer"]
            
            buttons = []
            custom_buttons_str = faq.get("buttons")
            if custom_buttons_str:
                for line in custom_buttons_str.strip().split("\n"):
                    if "|" in line:
                        btn_text, raw_url = line.split("|", 1)
                        btn_text = btn_text.strip()
                        raw_url = raw_url.strip()
                        
                        if raw_url == "wa_admin":
                            resolved_url = await ReplyService.get_wa_link()
                        elif raw_url == "wa_claim":
                            resolved_url = await ReplyService.get_wa_link("Halo admin, saya mau klaim garansi")
                        elif raw_url == "wa_order":
                            resolved_url = await ReplyService.get_wa_link("Halo admin, saya mau order")
                        elif raw_url == "autoorder":
                            resolved_url = await settings_svc.get_setting("autoorder_bot_link", "")
                        elif raw_url == "channel":
                            resolved_url = await settings_svc.get_setting("channel_link", "")
                        else:
                            resolved_url = raw_url
                            
                        if resolved_url:
                            buttons.append({"text": btn_text, "url": resolved_url})
            else:
                # Default fallback buttons (original logic)
                wa_url = await ReplyService.get_wa_link()
                if intent == "cara_beli":
                    buttons.append({"text": "💬 Chat Admin WA", "url": wa_url})
                    ao_link = await settings_svc.get_setting("autoorder_bot_link", "")
                    if ao_link:
                        buttons.append({"text": "⚡ Bot Autoorder", "url": ao_link})
                elif intent == "payment":
                    buttons.append({"text": "💬 Chat Admin WA", "url": wa_url})
                elif intent == "garansi":
                    buttons.append({"text": "💬 Klaim Garansi via WA", "url": await ReplyService.get_wa_link("Halo admin, saya mau klaim garansi")})
                
            return {"text": text, "buttons": buttons}

        # 3. Fallback Reply formatting
        else:
            # Query did not match anything
            fallback_faq = match_result["matched_object"]
            text = fallback_faq["answer"] if fallback_faq else (
                "Mohon maaf kak, Otan belum mengerti pertanyaan kakak.\n\n"
                "Jika ada pertanyaan khusus atau butuh bantuan lebih lanjut, kakak bisa langsung tanya ke admin WhatsApp kami ya."
            )
            
            buttons = []
            custom_buttons_str = fallback_faq.get("buttons") if fallback_faq else None
            if custom_buttons_str:
                for line in custom_buttons_str.strip().split("\n"):
                    if "|" in line:
                        btn_text, raw_url = line.split("|", 1)
                        btn_text = btn_text.strip()
                        raw_url = raw_url.strip()
                        
                        if raw_url == "wa_admin":
                            resolved_url = await ReplyService.get_wa_link()
                        elif raw_url == "wa_claim":
                            resolved_url = await ReplyService.get_wa_link("Halo admin, saya mau klaim garansi")
                        elif raw_url == "wa_order":
                            resolved_url = await ReplyService.get_wa_link("Halo admin, saya mau order")
                        elif raw_url == "autoorder":
                            resolved_url = await settings_svc.get_setting("autoorder_bot_link", "")
                        elif raw_url == "channel":
                            resolved_url = await settings_svc.get_setting("channel_link", "")
                        else:
                            resolved_url = raw_url
                            
                        if resolved_url:
                            buttons.append({"text": btn_text, "url": resolved_url})
            else:
                wa_msg = f"Tanya admin tentang {query_text[:30]}"
                wa_url = await ReplyService.get_wa_link(wa_msg)
                buttons = [
                    {"text": "💬 Tanya Admin WA", "url": wa_url}
                ]
            
            return {"text": text, "buttons": buttons}

    @staticmethod
    async def get_catalog_reply() -> dict:
        """Formats the full catalog message listing active products."""
        active_prods = await product_svc.get_active_products()
        
        if not active_prods:
            text = (
                "Saat ini katalog kami sedang kosong kak.\n\n"
                "Silakan langsung hubungi admin WhatsApp kami untuk menanyakan ketersediaan produk premium lainnya."
            )
            buttons = [
                {"text": "💬 Tanya Admin WA", "url": await ReplyService.get_wa_link()}
            ]
            return {"text": text, "buttons": buttons}
            
        prod_lines = []
        for p in active_prods:
            category_prefix = f"[{p['category']}] " if p["category"] else ""
            variants = await product_svc.get_variants_for_product(p["id"])
            if variants:
                min_price = min(v["price"] for v in variants)
                price_suffix = f" (Mulai Rp {min_price:,.0f})".replace(",", ".")
            else:
                price_suffix = ""
            prod_lines.append(f"• {category_prefix}**{p['name']}**{price_suffix}")
            
        product_list = "\n".join(prod_lines)
        
        text = (
            f"Kami menyediakan beberapa app premium digital kak.\n\n"
            f"Beberapa yang bisa dicek:\n"
            f"{product_list}\n\n"
            f"Kakak mau cek app yang mana?"
        )
        
        buttons = [
            {"text": "💬 Chat Admin WA", "url": await ReplyService.get_wa_link()}
        ]
        
        return {"text": text, "buttons": buttons}

reply_svc = ReplyService()
