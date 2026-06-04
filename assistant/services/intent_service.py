import re
from rapidfuzz import process, fuzz
from database import db
from services.product_service import product_svc
from services.faq_service import faq_svc

class IntentService:
    @staticmethod
    async def match_intent(query: str) -> dict:
        """
        Processes a raw user query and matches it to either:
        1. An FAQ template intent (e.g. cara_beli, payment, garansi)
        2. A product catalog match (checking product name & aliases using RapidFuzz)
        
        Returns a dict:
        {
            "type": "faq" | "product" | "fallback",
            "matched_id": int | None,
            "matched_ref": str | None,   # intent name or product name
            "matched_object": dict | None,
            "confidence": float
        }
        """
        cleaned_query = query.strip().lower()
        if not cleaned_query:
            return {"type": "fallback", "matched_id": None, "matched_ref": "fallback", "matched_object": None, "confidence": 100.0}

        # 1. Match FAQ Templates first by keyword check
        active_faqs = await faq_svc.get_active_faqs()
        for faq in active_faqs:
            if faq["intent"] == "fallback":
                continue
            # Split keywords by comma
            keywords = [k.strip().lower() for k in faq["keywords"].split(",") if k.strip()]
            for kw in keywords:
                # Use regex word boundary check or exact substring
                pattern = r'\b' + re.escape(kw) + r'\b'
                if re.search(pattern, cleaned_query):
                    return {
                        "type": "faq",
                        "matched_id": faq["id"],
                        "matched_ref": faq["intent"],
                        "matched_object": faq,
                        "confidence": 100.0
                    }

        # 2. Match Products (Name and Aliases)
        active_products = await product_svc.get_active_products()
        if not active_products:
            # Fallback to fallback FAQ
            fallback_faq = await faq_svc.get_faq_by_intent("fallback")
            return {"type": "fallback", "matched_id": fallback_faq["id"] if fallback_faq else None, "matched_ref": "fallback", "matched_object": fallback_faq, "confidence": 100.0}

        # Prepare choices: key is string to match, value is product dict
        choices = {}
        for p in active_products:
            choices[p["name"].lower()] = p
            # Fetch aliases for this product
            aliases = await product_svc.get_aliases_for_product(p["id"])
            for alias in aliases:
                choices[alias["alias_text"].lower()] = p

        # Check for direct substring matches first (fast and precise)
        # E.g. if user says "beli netflix dong", "netflix" matches "netflix" directly.
        direct_matches = []
        for term, product in choices.items():
            if term in cleaned_query:
                # Calculate simple word match length to prioritize longer matches
                direct_matches.append((term, product))
        
        if direct_matches:
            # Sort by longest term length first
            direct_matches.sort(key=lambda x: len(x[0]), reverse=True)
            matched_term, matched_product = direct_matches[0]
            return {
                "type": "product",
                "matched_id": matched_product["id"],
                "matched_ref": matched_product["name"],
                "matched_object": matched_product,
                "confidence": 100.0
            }

        # If no direct match, perform fuzzy match using RapidFuzz
        candidates = list(choices.keys())
        # We extract the single best match using token_set_ratio which works well for multi-word text
        best_match = process.extractOne(
            cleaned_query,
            candidates,
            scorer=fuzz.token_set_ratio
        )
        
        if best_match:
            matched_term, score, _ = best_match
            if score >= 75.0:  # Threshold for product name mismatch correction (e.g. canvaa -> canva)
                matched_product = choices[matched_term]
                return {
                    "type": "product",
                    "matched_id": matched_product["id"],
                    "matched_ref": matched_product["name"],
                    "matched_object": matched_product,
                    "confidence": score
                }

        # 3. Fallback if nothing matched
        fallback_faq = await faq_svc.get_faq_by_intent("fallback")
        return {
            "type": "fallback",
            "matched_id": fallback_faq["id"] if fallback_faq else None,
            "matched_ref": "fallback",
            "matched_object": fallback_faq,
            "confidence": 100.0
        }

intent_svc = IntentService()
