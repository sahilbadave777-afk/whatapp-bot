# Quick test: you + your friend, using Meta's free test number

**Cost: $0.** The bot runs in free mode (no AI, no API key to buy). Shopify, Meta's test number and ngrok are all free.

This doesn't touch your real business number. Meta gives every developer app a free
test number that can chat with up to 5 phone numbers you add.

Total time: about 30 minutes.

---

## Step 1 — Get the code running on your computer
In VS Code, open the `rps-whatsapp-bot` folder, then in the terminal:

```bash
python -m venv venv
venv\Scripts\activate            # Mac: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # Mac: cp .env.example .env
```

Fill these into `.env` now:
- `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` (README step 1)
- Leave `BOT_MODE=free` — no Claude key needed.

**Check it works without WhatsApp:**
```bash
python chat_test.py
```
Ask: `do you have 110.2207` — you should get the Automann camshaft kit with price and link.
Then reply `1` to see full details. If this works, the Shopify connection is good. Type `quit`.

## Step 2 — Meta test number
1. Go to **developers.facebook.com** → **My Apps** → **Create app** → choose **Business** type
   (or "Connect with customers through WhatsApp" use case).
2. In the app, open **WhatsApp → API Setup**. Meta shows a **test number** automatically.
3. Copy into `.env`:
   - **Temporary access token** → `WHATSAPP_TOKEN` (lasts 24 hours — fine for testing; click "Generate" again tomorrow)
   - **Phone number ID** → `WHATSAPP_PHONE_NUMBER_ID`
4. **App settings → Basic → App secret** → `WHATSAPP_APP_SECRET`
5. Back in API Setup, under **To**, click **Manage phone number list** → add **your number**
   and **your friend's number**. Each of you gets a code on WhatsApp to confirm.
6. In `.env`, set both numbers (country code, digits only — US numbers start with 1):
   ```
   ALLOWED_NUMBERS=1732XXXXXXX,1908XXXXXXX
   ```
7. Click **Send message** in API Setup once — you'll get Meta's "hello world" from the test number.
   Save that contact on your phone as "RPS Bot Test".

## Step 3 — Start the bot and give Meta a public link
Terminal 1:
```bash
uvicorn app:app --port 8000
```
Terminal 2 (install ngrok free from ngrok.com, sign in once with `ngrok config add-authtoken ...`):
```bash
ngrok http 8000
```
Copy the `https://....ngrok-free.app` link it shows.

## Step 4 — Connect the webhook
**WhatsApp → Configuration → Webhook → Edit**
- Callback URL: `https://....ngrok-free.app/webhook`
- Verify token: `rps-verify-123` (or whatever `WHATSAPP_VERIFY_TOKEN` is in `.env`)
- **Verify and save** → then next to **messages** click **Subscribe**.

## Step 5 — Text it
From your WhatsApp (and your friend's), message the test number:
- `hi`
- `do you have brake fluid?`
- `110.2207`  (part number)
- `078254050188`  (barcode)
- reply `1` or `2` after a list → full details + photo
- something you don't sell, like `iphone charger` → it should say so / offer related items
- `agent` → your contact info

You'll see each message logged in Terminal 1.

---

## If something doesn't work
| Problem | Fix |
|---|---|
| "Verify and save" fails | Bot isn't running, ngrok link is wrong, or verify token doesn't match `.env` |
| Message arrives (Terminal 1 logs it) but no reply | Token expired (24 h) → generate a new one, update `.env`, restart uvicorn |
| Nothing logged at all | Didn't click **Subscribe** on `messages`, or your number isn't in the **To** list |
| Log says "ignoring message from …" | That number is missing from `ALLOWED_NUMBERS` (check country code) |
| Reply error 131030 in log | Recipient not added in Meta's **To** list |
| ngrok link changed | Free ngrok gives a new link each restart → update it in Webhook settings |

When you're happy with it, follow README.md to move to your real number and host it online.
