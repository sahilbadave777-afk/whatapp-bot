"""WhatsApp webhook server.

Run locally:   uvicorn app:app --port 8000
Meta calls:    GET  /webhook  (one-time verification)
               POST /webhook  (every incoming customer message)
"""
import logging
import threading
from collections import OrderedDict

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

import config
import whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = FastAPI(title=f"{config.BUSINESS_NAME} WhatsApp bot")
_agent = None
_seen_ids: OrderedDict[str, None] = OrderedDict()   # Meta sometimes delivers the same message twice
_user_locks: dict[str, threading.Lock] = {}          # answer one message at a time per customer


def agent():
    """Free mode (no AI) by default; Claude only when BOT_MODE=ai."""
    global _agent
    if _agent is None:
        if config.BOT_MODE == "ai":
            from agent import SalesAgent
            _agent = SalesAgent()
        else:
            from simple_bot import SimpleBot
            _agent = SimpleBot()
        log.info("bot mode: %s", config.BOT_MODE)
    return _agent


@app.get("/")
def health():
    return {"ok": True, "bot": config.BUSINESS_NAME, "mode": config.BOT_MODE}


@app.get("/webhook")
def verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    if mode == "subscribe" and token == config.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not whatsapp.valid_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Bad signature")

    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                if _duplicate(msg.get("id")):
                    continue
                if config.ALLOWED_NUMBERS and msg.get("from") not in config.ALLOWED_NUMBERS:
                    log.info("test mode: ignoring message from %s (not in ALLOWED_NUMBERS)", msg.get("from"))
                    continue
                background.add_task(handle_message, msg, names.get(msg.get("from"), ""))
    # Reply 200 right away; Meta retries if we're slow.
    return {"ok": True}


def handle_message(msg: dict, name: str) -> None:
    phone = msg.get("from")
    mtype = msg.get("type")
    text = _extract_text(msg)
    whatsapp.mark_read_and_typing(msg.get("id"))

    if not text:
        whatsapp.send_text(phone, "Thanks! I can help best with text — please type the part name, "
                                  "part number or barcode you're looking for.")
        log.info("non-text message (%s) from %s", mtype, phone)
        return

    lock = _user_locks.setdefault(phone, threading.Lock())
    with lock:
        try:
            reply = agent().reply(phone, name, text)
            whatsapp.send_text(phone, reply.text)
            for url, caption in reply.photos:
                whatsapp.send_image(phone, url, caption)
            log.info("answered %s: %r", phone, text[:80])
        except Exception:  # noqa: BLE001
            log.exception("failed handling message from %s", phone)
            whatsapp.send_text(phone, f"Sorry, something went wrong on our side. Please try again in a "
                                      f"minute, or {config.BUSINESS_CONTACT}.")


def _extract_text(msg: dict) -> str:
    t = msg.get("type")
    if t == "text":
        return msg["text"].get("body", "").strip()
    if t == "interactive":
        i = msg.get("interactive", {})
        return (i.get("button_reply") or i.get("list_reply") or {}).get("title", "").strip()
    if t == "button":
        return msg.get("button", {}).get("text", "").strip()
    if t == "image":
        return msg.get("image", {}).get("caption", "").strip()  # photo with a caption like a part number
    return ""


def _duplicate(msg_id: str | None) -> bool:
    if not msg_id:
        return False
    if msg_id in _seen_ids:
        return True
    _seen_ids[msg_id] = None
    if len(_seen_ids) > 5000:
        _seen_ids.popitem(last=False)
    return False
