"""Sends messages through the WhatsApp Cloud API and checks Meta's webhook signatures."""
import hashlib
import hmac
import logging
import requests

import config

log = logging.getLogger("whatsapp")
MAX_TEXT = 4000  # WhatsApp limit is 4096 characters


def _url() -> str:
    return f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"


def _post(payload: dict) -> dict | None:
    payload = {"messaging_product": "whatsapp", **payload}
    r = requests.post(
        _url(),
        json=payload,
        headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
        timeout=20,
    )
    if r.status_code >= 400:
        log.error("WhatsApp send failed %s: %s", r.status_code, r.text[:500])
        return None
    return r.json()


def send_text(to: str, text: str) -> None:
    text = (text or "").strip()
    while text:
        chunk, text = _split(text)
        _post({"to": to, "type": "text", "text": {"body": chunk, "preview_url": True}})


def send_image(to: str, image_url: str, caption: str = "") -> None:
    _post({"to": to, "type": "image", "image": {"link": image_url, "caption": caption[:1000]}})


def mark_read_and_typing(message_id: str) -> None:
    """Shows blue ticks + 'typing…' while the bot thinks. Harmless if it fails."""
    try:
        _post({"status": "read", "message_id": message_id, "typing_indicator": {"type": "text"}})
    except Exception:  # noqa: BLE001
        pass


def subscribe_app() -> bool:
    """Tell Meta to send this WhatsApp Business Account's messages to our app (safe to call every start)."""
    if not (config.WHATSAPP_TOKEN and config.WHATSAPP_BUSINESS_ACCOUNT_ID):
        return False
    url = f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{config.WHATSAPP_BUSINESS_ACCOUNT_ID}/subscribed_apps"
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}, timeout=20)
        ok = r.status_code < 400 and r.json().get("success") is True
        log.info("WABA subscribe: %s %s", r.status_code, r.text[:200])
        return ok
    except Exception as e:  # noqa: BLE001
        log.error("WABA subscribe failed: %s", e)
        return False


def valid_signature(raw_body: bytes, header: str | None) -> bool:
    """Rejects fake webhook calls. Skipped only if no app secret is configured (local testing)."""
    if not config.WHATSAPP_APP_SECRET:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(config.WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def _split(text: str) -> tuple[str, str]:
    if len(text) <= MAX_TEXT:
        return text, ""
    cut = text.rfind("\n", 0, MAX_TEXT)
    if cut < MAX_TEXT // 2:
        cut = MAX_TEXT
    return text[:cut].rstrip(), text[cut:].lstrip()
