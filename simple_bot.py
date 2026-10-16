"""FREE mode: no AI, no API cost. Searches Shopify directly and replies in a friendly, human tone.

Customer can:
  - type a product name, brand, part number or barcode  -> list of matches
  - reply with a number (e.g. "2")                        -> details + photo of that item
  - say hi / thanks / bye                                 -> friendly reply
  - ask about hours, location, shipping, payment, returns -> business info (set in config / .env)
  - ask for a person / to order / bulk pricing            -> your contact info
"""
import random
import re
import time

import config
from models import Reply
from shopify_client import ShopifyClient

# ---------------------------------------------------------------- small talk
GREETINGS = re.compile(
    r"^(hi+|hey+|hello+|hii+|helo|yo|hola|namaste|sup|good (morning|afternoon|evening|day)|"
    r"morning|evening|menu|start|help|hi there|hello there)[\s!.?]*$", re.I)
THANKS = re.compile(r"^(thanks?( you| u)?( so much| a lot)?|thx|ty|tysm|ok(ay)?|great|cool|perfect|"
                    r"awesome|nice|got it|sounds good|good|great thanks|ok thanks|alright)[\s!.?]*$", re.I)
BYE = re.compile(r"^(bye+|goodbye|see (you|ya)|later|take care|good night|gn|ttyl|cya)[\s!.?]*$", re.I)
HOW_ARE_YOU = re.compile(r"\b(how are you|how r u|how are u|hows it going|how's it going|whats up|what's up)\b", re.I)
YES_NO = re.compile(r"^(yes|yeah|yep|yup|no|nope|nah|sure)[\s!.?]*$", re.I)

HUMAN_WORDS = {"agent", "human", "person", "representative", "rep", "someone", "sales", "order", "call",
               "bulk", "wholesale", "account", "quote", "invoice", "speak", "talk"}

# business questions -> answers come from config (edit them in .env / Render)
INFO_TOPICS = [
    (re.compile(r"\b(hours?|open|close|closing|opening|timing|time do you|what time)\b", re.I), "hours"),
    (re.compile(r"\b(where|location|address|located|directions|store|warehouse|map)\b", re.I), "location"),
    (re.compile(r"\b(ship|shipping|deliver|delivery|courier|freight|pickup|pick up)\b", re.I), "shipping"),
    (re.compile(r"\b(pay|payment|credit card|card|zelle|cash|check|cheque|net 30|terms)\b", re.I), "payment"),
    (re.compile(r"\b(return|refund|warranty|exchange|defective|broken)\b", re.I), "returns"),
    (re.compile(r"\b(website|site|online|catalog|catalogue)\b", re.I), "website"),
]

FILLER = re.compile(
    r"\b(do|does|did|you|u|guys|have|got|sell|carry|any|anything|is|are|there|the|a|an|i|im|i'm|need|want|"
    r"looking|for|please|pls|plz|price|prices|pricing|cost|of|how|much|what|whats|what's|in|stock|available|"
    r"availability|can|could|get|me|show|find|search|some|your|my|it|this|that|hi|hello|hey|thanks|"
    r"bro|sir|madam|dear|also|and|or|with|about|know|tell|check|like|would|wanna|gimme)\b",
    re.I,
)


class SimpleBot:
    def __init__(self, shopify: ShopifyClient | None = None):
        self.shopify = shopify or ShopifyClient()
        self.last_list: dict[str, tuple[float, list[dict]]] = {}   # phone -> (time, products shown)
        self.greeted: dict[str, float] = {}                         # phone -> last greeting time

    # ------------------------------------------------------------ main entry
    def reply(self, phone: str, customer_name: str, text: str) -> Reply:
        raw = text.strip()
        low = raw.lower().strip()
        first = (customer_name or "").split()[0] if customer_name else ""
        returning = phone in self.greeted and time.time() - self.greeted[phone] < 6 * 3600
        self.greeted[phone] = time.time()

        # --- small talk ---
        if GREETINGS.match(low):
            return Reply(self._welcome(first, returning))
        if HOW_ARE_YOU.search(low) and len(low.split()) <= 8:
            return Reply(f"I'm doing great, thanks for asking{', ' + first if first else ''}! 😊 "
                         "What part can I help you find today?")
        if THANKS.match(low):
            return Reply(random.choice([
                "You're welcome! 😊 Anything else I can look up for you?",
                "Happy to help! Send another part name or number anytime.",
                "Anytime! Let me know if you need anything else.",
            ]))
        if BYE.match(low):
            return Reply(random.choice([
                f"Take care{', ' + first if first else ''}! Message me anytime you need a part. 👋",
                "Bye for now! We're here whenever you need us. 👋",
            ]))
        if YES_NO.match(low):
            return Reply("Sure — just send me the part name, brand, part number or barcode you're looking for.")

        # --- business questions (hours, location, shipping...) ---
        info = self._info_answer(low)
        if info:
            return Reply(info)

        # --- wants a person / to place an order ---
        if any(re.search(rf"\b{w}\b", low) for w in HUMAN_WORDS) and len(low.split()) <= 8:
            return Reply(f"Of course! Our team will be glad to help with orders, bulk pricing or anything else.\n\n"
                         f"📞 {config.BUSINESS_CONTACT}\n\n"
                         "Meanwhile, I can still check any part's price and availability for you — just send me the name or number.")

        # --- customer picked a number from the last list ---
        if re.fullmatch(r"#?\d{1,2}", low):
            return self._pick(phone, int(low.lstrip("#")))

        # --- product search ---
        query = self._clean_query(raw)
        if not query:
            return Reply("I'd love to help! Send me a part name, brand, part number or barcode and I'll check it for you. 🔎")

        results = self.shopify.search(query, limit=5)
        exact = self._exact_match(query, results)
        if exact:
            results = [exact]

        available = [p for p in results if p["in_stock"]]
        unavailable = [p for p in results if not p["in_stock"]]

        if not available:
            base_id = results[0]["id"] if results else None
            related = self.shopify.related(product_id=base_id, keywords=None if base_id else query, limit=5)
            if results:
                head = f"Hmm, *{results[0]['title']}* is currently unavailable. 😕"
            else:
                head = f"Sorry, I couldn't find anything for \"{query}\" in our catalog. 😕"
            if related:
                self._remember(phone, related)
                return Reply(head + "\n\nBut here are some related items we do have:\n\n"
                             + self._list(related) + self._footer())
            return Reply(head + "\n\nCould you try a different name, brand or part number? "
                         f"Or our team can check for you: {config.BUSINESS_CONTACT}.")

        shown = available + unavailable
        self._remember(phone, shown)

        if len(shown) == 1:
            return self._details(shown[0], intro="Found it! 👍\n\n")

        intro = random.choice([
            f"Here's what I found for \"{query}\":",
            f"Great, we have a few options for \"{query}\":",
            f"Sure! Here are our matches for \"{query}\":",
        ])
        return Reply(intro + "\n\n" + self._list(shown) + self._footer())

    # ------------------------------------------------------------ helpers
    def _info_answer(self, low: str) -> str | None:
        for pattern, topic in INFO_TOPICS:
            if pattern.search(low):
                answer = getattr(config, f"INFO_{topic.upper()}", "")
                if answer:
                    return answer
                return (f"Good question! For {topic} details please reach our team: {config.BUSINESS_CONTACT}.\n\n"
                        "I can also check any part's price and availability for you right here.")
        return None

    def _pick(self, phone: str, n: int) -> Reply:
        saved = self.last_list.get(phone)
        if not saved or time.time() - saved[0] > 3 * 3600:
            return Reply("Send me a part name or number first, then reply with a number from the list. 🙂")
        items = saved[1]
        if not 1 <= n <= len(items):
            return Reply(f"Please reply with a number from 1 to {len(items)}.")
        fresh = self.shopify.get(items[n - 1]["id"]) or items[n - 1]  # re-check live price/stock
        return self._details(fresh)

    def _details(self, p: dict, intro: str = "") -> Reply:
        lines = [f"*{p['title']}*"]
        lines.append(f"💲 Price: {p['price']}" if p.get("price") else "💲 Price: please contact us for pricing")
        lines.append("📦 " + ("In stock — available to order" if p["in_stock"] else "Currently unavailable"))
        if p.get("qty_available") is not None:
            lines.append(f"🔢 Quantity: {p['qty_available']}")
        v = (p.get("variants") or [{}])[0]
        if v.get("sku"):
            lines.append(f"🔧 Part #: {v['sku']}")
        if v.get("barcode"):
            lines.append(f"🏷 Barcode: {v['barcode']}")
        if p.get("brand"):
            lines.append(f"🏭 Brand: {p['brand']}")
        if p.get("description"):
            d = p["description"]
            lines.append("\n" + (d[:300] + "…" if len(d) > 300 else d))
        lines.append(f"\n🔗 {p['url']}")
        lines.append(f"\nWant to order or need a bulk price? {config.BUSINESS_CONTACT}.")

        photos = []
        if config.SEND_PRODUCT_PHOTOS and p.get("_image"):
            photos.append((p["_image"], p["title"] + (f" - {p['price']}" if p.get("price") else "")))

        text = intro + "\n".join(lines)
        if not p["in_stock"]:
            related = self.shopify.related(product_id=p["id"], limit=3)
            if related:
                text += "\n\nYou might like these instead:\n\n" + self._list(related, numbered=False)
        return Reply(text, photos)

    @staticmethod
    def _list(items: list[dict], numbered: bool = True) -> str:
        out = []
        for i, p in enumerate(items, 1):
            price = p["price"] or "Call for price"
            status = "✅ In stock" if p["in_stock"] else "❌ Unavailable"
            prefix = f"{i}. " if numbered else "• "
            out.append(f"{prefix}*{p['title']}*\n   {price} · {status}\n   {p['url']}")
        return "\n\n".join(out)

    @staticmethod
    def _footer() -> str:
        return "\n\nReply with a number (like *1*) and I'll send full details and a photo. 📸"

    def _remember(self, phone: str, items: list[dict]) -> None:
        self.last_list[phone] = (time.time(), items)

    @staticmethod
    def _clean_query(text: str) -> str:
        stripped = text.strip().strip("?.! ")
        # keep part numbers / barcodes exactly as typed
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
    def _welcome(first: str, returning: bool) -> str:
        if returning:
            return (f"Welcome back{', ' + first if first else ''}! 👋 What can I find for you this time? "
                    "Send a part name, brand, part number or barcode.")
        hi = f"Hi {first}! 👋 " if first else "Hi there! 👋 "
        return (f"{hi}Welcome to *{config.BUSINESS_NAME}* — thanks for messaging us!\n\n"
                "I'm the RPS parts assistant. Send me a *part name*, *brand*, *part number* or *barcode* "
                "and I'll check the price and availability for you right away.\n\n"
                "For example:\n• brake fluid\n• oil filter\n• Automann camshaft\n• 110.2207\n\n"
                f"Need a person, an order or bulk pricing? {config.BUSINESS_CONTACT}.")
