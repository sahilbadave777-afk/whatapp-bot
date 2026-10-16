"""All settings come from environment variables (or a .env file)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required setting: {name} (add it to your .env file)")
    return value or ""


# --- WhatsApp Cloud API (Meta) ---
WHATSAPP_TOKEN = _get("WHATSAPP_TOKEN")              # permanent System User token
WHATSAPP_PHONE_NUMBER_ID = _get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_BUSINESS_ACCOUNT_ID = _get("WHATSAPP_BUSINESS_ACCOUNT_ID")  # WABA id; lets the bot subscribe itself on startup
WHATSAPP_VERIFY_TOKEN = _get("WHATSAPP_VERIFY_TOKEN", "rps-verify-123")
WHATSAPP_APP_SECRET = _get("WHATSAPP_APP_SECRET")    # used to check Meta's webhook signature
GRAPH_API_VERSION = _get("GRAPH_API_VERSION", "v26.0")

# --- Shopify ---
SHOPIFY_STORE = _get("SHOPIFY_STORE")                # e.g. rps-distributors.myshopify.com
SHOPIFY_API_VERSION = _get("SHOPIFY_API_VERSION", "2026-07")
# Option A (apps made in the Dev Dashboard, 2026+): client credentials -> token auto-refreshes
SHOPIFY_CLIENT_ID = _get("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = _get("SHOPIFY_CLIENT_SECRET")
# Option B (an older custom app that already gave you a shpat_ token)
SHOPIFY_ADMIN_TOKEN = _get("SHOPIFY_ADMIN_TOKEN")
PUBLIC_STORE_URL = _get("PUBLIC_STORE_URL", "https://rpsdistributorsinc.com").rstrip("/")

# --- Bot mode ---
# "free" = no AI, no cost (direct Shopify search).  "ai" = Claude replies (needs ANTHROPIC_API_KEY).
BOT_MODE = _get("BOT_MODE", "free").lower()

# --- Claude (only used when BOT_MODE=ai) ---
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-sonnet-5-5")

# --- Business behaviour ---
BUSINESS_NAME = _get("BUSINESS_NAME", "RPS Distributors Inc.")
BUSINESS_CONTACT = _get("BUSINESS_CONTACT", "call us or email sales@rpsdistributorsinc.com")
SHOW_EXACT_STOCK = _get("SHOW_EXACT_STOCK", "false").lower() == "true"  # false = "In stock"/"Out of stock" only
SEND_PRODUCT_PHOTOS = _get("SEND_PRODUCT_PHOTOS", "true").lower() == "true"

# --- Answers to common customer questions (leave blank to point them to BUSINESS_CONTACT) ---
INFO_HOURS = _get("INFO_HOURS")          # e.g. "We're open Mon-Fri 8am-5pm and Sat 9am-1pm (Eastern)."
INFO_LOCATION = _get("INFO_LOCATION")    # e.g. "We're at 123 Main St, Edison, NJ. Pickup is welcome!"
INFO_SHIPPING = _get("INFO_SHIPPING")    # e.g. "We ship nationwide; local delivery in NJ. Most orders ship same day."
INFO_PAYMENT = _get("INFO_PAYMENT")      # e.g. "We accept card, Zelle, check and cash. Net-30 for approved accounts."
INFO_RETURNS = _get("INFO_RETURNS")      # e.g. "Returns accepted within 30 days in original packaging."
INFO_WEBSITE = _get("INFO_WEBSITE", f"You can browse our full catalog anytime at {PUBLIC_STORE_URL} 🛒")
MAX_HISTORY_TURNS = int(_get("MAX_HISTORY_TURNS", "12"))

# Test mode: only these numbers get replies (comma-separated, with country code, e.g. 17325551234,17325559876).
# Leave empty to answer everyone.
ALLOWED_NUMBERS = {"".join(ch for ch in n if ch.isdigit()) for n in _get("ALLOWED_NUMBERS").split(",") if n.strip()}
