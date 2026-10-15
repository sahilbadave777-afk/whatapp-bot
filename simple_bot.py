"""FREE mode: no AI, no API cost. Searches Shopify directly and replies with a numbered list.

Customer can:
  - type a product name, brand, part number or barcode  -> list of matches
  - reply with a number (e.g. "2")                        -> details + photo of that item
  - type "hi" / "menu"                                    -> welcome message
  - type "agent" / "order" / "human"                      -> your contact info
"""
import re
import time

import config
from models import Reply
from shopify_client import ShopifyClient

GREETINGS = {"hi", "hello", "hey", "hii", "hola", "namaste", "menu", "start", "help", "good morning",
             "good afternoon", "good evening"}
HUMAN_WORDS = {"agent", "human", "person", "representative", "order", "call", "bulk", "wholesale account"}
THANKS = {"thanks", "thank you", "thx", "ok", "okay", "great", "cool"}
FILLER = re.compile(
    r"\b(do|does|did|you|u|guys|have|got|sell|carry|any|anything|is|are|there|the|a|an|i|need|want|"
    r"looking|for|please|pls|plz|price|prices|cost|of|how|much|what|whats|in|stock|available|"
    r"can|get|me|show|find|search|some|your|my|it|this|that)\b",
    re.I,
)


class SimpleBot:
    def __init__(self, shopify: ShopifyClient | None = None):
        self.shopify = shopify or ShopifyClient()
        self.last_list: dict[str, tuple[float, list[dict]]] = {}  # phone -> (time, products shown)

    def reply(self, phone: str, customer_name: str, text: str) -> Reply:
        raw = text.strip()
        low = raw.lower().strip(" !.?")

        if low in GREETINGS:
            return Reply(self._welcome(customer_name))
        if low in THANKS:
            return Reply("You're welcome! Send another part name or number anytime.")
        if any(re.search(rf"\b{w}\b", low) for w in HUMAN_WORDS) and len(low.split()) <= 6:
            return Reply(f"Sure! To order, for bulk pricing, or to talk to our team: {config.BUSINESS_CONTACT}.")

        # Customer picked a number from the last list
        if re.fullmatch(r"#?\d{1,2}", low):
            return self._pick(phone, int(low.lstrip("#")))

        query = self._clean_query(raw)
        if not query:
            return Reply(self._welcome(customer_name))

        results = self.shopify.search(query, limit=5)
        exact = self._exact_match(query, results)
        if exact:
            results = [exact]

        available = [p for p in results if p["in_stock"]]
        unavailable = [p for p in results if not p["in_stock"]]

        # Nothing found, or nothing available -> offer related items
        if not available:
            base_id = results[0]["id"] if results else None
            related = self.shopify.related(product_id=base_id, keywords=None if base_id else query, limit=5)
            if results:
                head = f"*{results[0]['title']}* is currently unavailable."
            else:
                head = f"Sorry, we couldn't find \"{query}\" in our catalog."
            if related:
                self._remember(phone, related)
                return Reply(head + "\n\nRelated items we have:\n\n" + self._list(related) + self._footer())
            return Reply(head + f"\n\nTry a different name or part number, or {config.BUSINESS_CONTACT}.")

        shown = available + unavailable
        self._remember(phone, shown)

        # One clear match -> full details + photo
        if len(shown) == 1:
            return self._details(shown[0])

        return Reply(f"Here's what we found for \"{query}\":\n\n" + self._list(shown) + self._footer())

    # ---------- helpers ----------
    def _pick(self, phone: str, n: int) -> Reply:
        saved = self.last_list.get(phone)
        if not saved or time.time() - saved[0] > 3 * 3600:
            return Reply("Please send a product name or part number first.")
        items = saved[1]
        if not 1 <= n <= len(items):
            return Reply(f"Please reply with a number from 1 to {len(items)}.")
        fresh = self.shopify.get(items[n - 1]["id"]) or items[n - 1]  # re-check live price/stock
        return self._details(fresh)

    def _details(self, p: dict) -> Reply:
        lines = [f"*{p['title']}*"]
        lines.append(f"Price: {p['price']}" if p.get("price") else "Price: please contact us for pricing")
        lines.append("Availability: " + ("✅ Available" if p["in_stock"] else "❌ Currently unavailable"))
        if p.get("qty_available") is not None:
            lines.append(f"Quantity: {p['qty_available']}")
        v = (p.get("variants") or [{}])[0]
        if v.get("sku"):
            lines.append(f"Part #: {v['sku']}")
        if v.get("barcode"):
            lines.append(f"Barcode: {v['barcode']}")
        if p.get("brand"):
            lines.append(f"Brand: {p['brand']}")
        if p.get("description"):
            d = p["description"]
            lines.append("\n" + (d[:300] + "…" if len(d) > 300 else d))
        lines.append(f"\n{p['url']}")
        lines.append(f"\nTo order: {config.BUSINESS_CONTACT}.")

        photos = []
        if config.SEND_PRODUCT_PHOTOS and p.get("_image"):
            photos.append((p["_image"], p["title"] + (f" - {p['price']}" if p.get("price") else "")))

        text = "\n".join(lines)
        if not p["in_stock"]:
            related = self.shopify.related(product_id=p["id"], limit=3)
            if related:
                text += "\n\nAvailable alternatives:\n\n" + self._list(related, numbered=False)
        return Reply(text, photos)

    @staticmethod
    def _list(items: list[dict], numbered: bool = True) -> str:
        out = []
        for i, p in enumerate(items, 1):
            price = p["price"] or "Call for price"
            status = "✅" if p["in_stock"] else "❌ unavailable"
            prefix = f"{i}. " if numbered else "• "
            out.append(f"{prefix}*{p['title']}*\n   {price} {status}\n   {p['url']}")
        return "\n\n".join(out)

    @staticmethod
    def _footer() -> str:
        return "\n\nReply with a number (like *1*) for details and a photo."

    def _remember(self, phone: str, items: list[dict]) -> None:
        self.last_list[phone] = (time.time(), items)

    @staticmethod
    def _clean_query(text: str) -> str:
        # keep part numbers/barcodes exactly as typed
        stripped = text.strip().strip("?.! ")
        if re.fullmatch(r"[A-Za-z0-9\-\.\/]{3,30}", stripped) and any(c.isdigit() for c in stripped):
            return stripped
        q = FILLER.sub(" ", text)
        q = re.sub(r"[^\w\s\-\.\/']", " ", q)
        return re.sub(r"\s+", " ", q).strip(" .-")

    @staticmethod
    def _exact_match(query: str, results: list[dict]) -> dict | None:
        q = query.lower()
        for p in results:
            for v in p.get("variants", []):
                if q in {(v.get("sku") or "").lower(), (v.get("barcode") or "").lower()}:
                    return p
        return None

    @staticmethod
    def _welcome(name: str) -> str:
        hi = f"Hi {name.split()[0]}! " if name else "Hi! "
        return (f"{hi}Welcome to *{config.BUSINESS_NAME}* 🚚\n\n"
                "Send me a *part name*, *brand*, *part number* or *barcode* and I'll check price and availability.\n\n"
                "Examples:\n• brake fluid\n• Automann camshaft\n• 110.2207\n\n"
                f"To order or talk to our team: {config.BUSINESS_CONTACT}.")
