"""Claude reads the customer's message, looks things up in Shopify with tools, and writes the reply."""
import json
import logging
import time
from collections import defaultdict, deque

import anthropic

import config
from models import Reply
from shopify_client import ShopifyClient

log = logging.getLogger("agent")

SYSTEM_PROMPT = f"""You are the WhatsApp sales assistant for {config.BUSINESS_NAME}, a wholesale truck and auto parts distributor (website: {config.PUBLIC_STORE_URL}).

ACCURACY RULES (most important):
- Every product name, price, part number, SKU, barcode, brand and availability you mention MUST come from a tool result in this conversation. Never guess, round, or invent them.
- If price is null, say "please contact us for pricing" — never quote $0.
- "in_stock": true means available to order; false means currently unavailable.
- If you're not sure two parts fit the same vehicle or application, say so and suggest the customer confirm the part number. Never claim fitment the data doesn't state.

HOW TO HELP:
- Always search before answering a product question. Part numbers, SKUs and barcodes are searched exactly.
- Try 2-3 different searches (synonyms, brand, part number, shorter wording) before concluding something isn't carried.
- If the exact item isn't found or isn't available, say so clearly, then call find_related_products and offer the closest available alternatives.
- For each product you list give: name, price, availability, and the product link.
- Show at most 5 products. If there are many matches, show the best ones and ask a narrowing question (brand, size, truck make).
- When one specific product is the clear answer, call send_product_photo for it.

STYLE (WhatsApp):
- Short and friendly. Plain text; *single asterisks* for bold. No markdown headings or tables.
- Reply in the customer's language.
- For orders, bulk/wholesale pricing, account questions, or if the customer wants a person: {config.BUSINESS_CONTACT}.
- Don't discuss topics unrelated to the store."""

TOOLS = [
    {
        "name": "search_products",
        "description": "Search the live Shopify catalog by words, brand, part number, SKU or barcode. Returns up to `limit` active products with price, availability and link.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "e.g. 'DOT 3 brake fluid', 'Automann camshaft', '110.2207', '078254050188'"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_product",
        "description": "Get full details (all variants, SKUs, description) for one product id from a search result.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    {
        "name": "find_related_products",
        "description": "Find available alternatives. Pass product_id (same category/type as that product) and/or keywords describing what the customer wanted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "keywords": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
            },
        },
    },
    {
        "name": "send_product_photo",
        "description": "Send the customer the product's photo (sent right after your text reply). Use for at most 2 products.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}},
            "required": ["product_id"],
        },
    },
]


class SalesAgent:
    def __init__(self, shopify: ShopifyClient | None = None, client: anthropic.Anthropic | None = None):
        self.shopify = shopify or ShopifyClient()
        self.client = client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        # per-customer chat history: phone -> deque of messages; plus last-seen time
        self.history: dict[str, deque] = defaultdict(lambda: deque(maxlen=config.MAX_HISTORY_TURNS * 2))
        self.last_seen: dict[str, float] = {}

    def reply(self, phone: str, customer_name: str, text: str) -> Reply:
        self._expire(phone)
        hist = self.history[phone]
        messages = list(hist) + [{"role": "user", "content": text}]
        products_seen: dict[str, dict] = {}
        photos: list[tuple[str, str]] = []

        system = SYSTEM_PROMPT + (f"\nThe customer's WhatsApp name is {customer_name}." if customer_name else "")

        final_text = ""
        for _ in range(8):  # max tool rounds
            resp = self.client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=1200,
                system=system,
                tools=TOOLS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                final_text = "".join(b.text for b in resp.content if b.type == "text").strip()
                break

            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                try:
                    out = self._run_tool(block.name, block.input, products_seen, photos)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out)})
                except Exception as e:  # noqa: BLE001
                    log.exception("tool %s failed", block.name)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Error: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})

        if not final_text:
            final_text = f"Sorry, I couldn't finish looking that up. Please try again or {config.BUSINESS_CONTACT}."

        # Keep only plain text turns in history (tool payloads are big and go stale)
        hist.append({"role": "user", "content": text})
        hist.append({"role": "assistant", "content": final_text})
        self.last_seen[phone] = time.time()
        return Reply(final_text, photos[:2] if config.SEND_PRODUCT_PHOTOS else [])

    # ---------- tools ----------
    def _run_tool(self, name: str, args: dict, seen: dict, photos: list):
        if name == "search_products":
            items = self.shopify.search(args["query"], args.get("limit", 5))
            return self._public(items, seen) or {"results": [], "note": "No match. Try other words or find_related_products."}
        if name == "get_product":
            item = self.shopify.get(args["product_id"])
            return (self._public([item], seen) or [{"error": "not found"}])[0]
        if name == "find_related_products":
            items = self.shopify.related(args.get("product_id"), args.get("keywords"), args.get("limit", 5))
            return self._public(items, seen) or {"results": [], "note": "No available alternatives found."}
        if name == "send_product_photo":
            pid = args["product_id"]
            item = seen.get(pid) or self.shopify.get(pid)
            if not item or not item.get("_image"):
                return {"sent": False, "reason": "This product has no photo."}
            caption = f"{item['title']}" + (f" - {item['price']}" if item.get("price") else "")
            photos.append((item["_image"], caption))
            return {"sent": True}
        raise ValueError(f"unknown tool {name}")

    @staticmethod
    def _public(items: list, seen: dict) -> list[dict]:
        out = []
        for it in items:
            if not it:
                continue
            seen[it["id"]] = it
            out.append({k: v for k, v in it.items() if not k.startswith("_")})
        return out

    def _expire(self, phone: str, idle_seconds: int = 6 * 3600) -> None:
        """Forget a conversation after 6 idle hours so old context doesn't confuse new questions."""
        if phone in self.last_seen and time.time() - self.last_seen[phone] > idle_seconds:
            self.history.pop(phone, None)
