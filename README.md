# RPS Distributors — WhatsApp Product Bot

> **Just want to try it with your own phone first? Follow TESTING.md.**

**Two modes** (set `BOT_MODE` in `.env`):
- `free` (default) — **no AI, $0.** Customer types a part name/number/barcode → numbered list → reply a number for details + photo.
- `ai` — Claude understands free-form questions ("need brakes for a 2018 Freightliner"). Needs a paid Anthropic API key and `pip install -r requirements-ai.txt`.

Customers message your WhatsApp Business number; the bot searches your **live Shopify catalog**
and replies with exact names, prices, part numbers, availability, links and photos.
If an item isn't carried or isn't available, it offers related products from the same store category.

```
Customer (WhatsApp) ──> Meta Cloud API ──> this server (/webhook)
                                              │  Claude decides what to look up
                                              ▼
                                       Shopify Admin API (live products)
```

**Example**
> Customer: do you have 110.2207?
> Bot: *Automann 110.2207 Camshaft Repair Kit Meritor Q and Q-Plus* — $15.92 — currently unavailable.
> Similar items available: *Automann 110.2204 Camshaft Repair Kit Meritor* — $15.92 — https://rpsdistributorsinc.com/products/…
> *(photo)*

## How it stays accurate
- Every price, SKU, barcode and availability comes from Shopify at the moment of the question — nothing is cached or guessed.
- $0 products are never quoted ("contact us for pricing").
- Part numbers, SKUs and barcodes are matched exactly (`sku:` / `barcode:` search).
- Your store doesn't track inventory counts, so availability = Shopify's "available for sale".
- Related products use your `rpsmm-…` category tags first (most specific), then product type and title words.

## Files
| File | What it does |
|---|---|
| `app.py` | Web server: receives WhatsApp messages, sends replies |
| `simple_bot.py` | Free mode: direct search, numbered lists, details |
| `agent.py` | AI mode: Claude instructions + the 4 tools it can use |
| `shopify_client.py` | Product search, details, related products |
| `whatsapp.py` | Sends text/photos, checks Meta's security signature |
| `config.py` / `.env` | Your keys and settings |

---

## Setup (about 1 hour)

### 1. Shopify API access (Dev Dashboard)
Since Jan 2026 Shopify no longer shows a copy-paste token for new custom apps.
1. Shopify admin → your profile menu → **Dev Dashboard** → **Create app** → name it "WhatsApp Bot".
2. **Versions** → scopes: `read_products`, `read_inventory` → **Release**.
3. **Home** → **Install** on your store.
4. **Settings** → copy **Client ID** and **Client secret** into `.env`.
   The bot exchanges them for a token automatically and refreshes it every 24 h.

### 2. Claude API key (only for `BOT_MODE=ai` — skip for free mode)
console.anthropic.com → API Keys → create → paste into `ANTHROPIC_API_KEY`. Add a small credit balance.

### 3. WhatsApp Cloud API
1. developers.facebook.com → **Create app** → type **Business** → add the **WhatsApp** product.
2. In **WhatsApp → API Setup**, add your business phone number (or test with Meta's free test number first).
   - If that number is currently in the WhatsApp Business **app**, Meta's onboarding offers to keep using the app
     on the same number alongside the API ("coexistence") — choose that if you still want to chat from your phone.
3. Copy the **Phone number ID** into `.env`.
4. Business Settings → **System users** → add an admin system user → **Generate token** with
   `whatsapp_business_messaging` + `whatsapp_business_management` → paste into `WHATSAPP_TOKEN` (this one doesn't expire).
5. App settings → Basic → copy **App secret** into `WHATSAPP_APP_SECRET`.

### 4. Put the bot online (Render.com, free tier works to start)
1. Push this folder to a private GitHub repo (`.env` is excluded — don't commit it).
2. Render → **New Web Service** → pick the repo.
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`
3. Add every line from your `.env` under **Environment**.
4. Open `https://YOUR-APP.onrender.com/` — you should see `{"ok": true}`.

> Free Render services sleep when idle, so the first reply after a quiet spell can take ~30 s. Use the paid "Starter" plan once customers rely on it.

### 5. Connect the webhook
WhatsApp → **Configuration** → Webhook:
- Callback URL: `https://YOUR-APP.onrender.com/webhook`
- Verify token: same word as `WHATSAPP_VERIFY_TOKEN`
- Click **Verify and save**, then **Subscribe** to the `messages` field.

### 6. Test
Message the number from your phone: "brake fluid", "110.2207", a barcode like "078254050188",
or something you don't carry to see the related-products offer.

## Run on your computer (for testing)
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # fill it in
uvicorn app:app --port 8000
# in another terminal, give Meta a public URL:
ngrok http 8000      # use the https URL + /webhook in step 5
```

## Settings worth knowing
- `SHOW_EXACT_STOCK=true` — show quantities (only useful once you turn on inventory tracking in Shopify).
- `SEND_PRODUCT_PHOTOS=false` — text only.
- `BUSINESS_CONTACT` — what the bot says for orders, bulk pricing, or "talk to a person".
- Change the bot's tone or rules in `SYSTEM_PROMPT` inside `agent.py`.

## Costs (approx.)
- WhatsApp: replies to customer-started chats are free within the 24-hour window.
- Claude: $0 in free mode; roughly 1–3 cents per customer question in AI mode.
- Hosting: free to ~$7/month on Render.

## Limits / next steps
- Chat memory is kept in server memory (resets on restart, 12 turns per customer). Fine for one server.
- Voice notes and photos without a caption get a "please type the part number" reply.
- Possible add-ons: order-status lookup by order number, alert a staff member on "talk to a person",
  read part numbers from customer photos.
