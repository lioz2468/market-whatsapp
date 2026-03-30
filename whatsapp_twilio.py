"""WhatsApp sender — Twilio provider.

Sending modes (tried in this order):
  1. Content Template  — if TWILIO_CONTENT_SID is set.
     Required for outbound sessions on production WhatsApp Business numbers.
     Template must have a single body variable {{1}} that receives the full text.
  2. Freeform body     — fallback (works on Twilio Sandbox, or within a 24-hour
     customer-service window on production numbers).

From address (one of):
  - TWILIO_MESSAGING_SERVICE_SID (MG...)  — recommended for production
  - TWILIO_WHATSAPP_FROM                  — direct number, e.g. whatsapp:+14155238886
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import config

log = logging.getLogger(__name__)


def _get_client():
    from twilio.rest import Client
    return Client(config.TWILIO_SID, config.TWILIO_AUTH_TOKEN)


def _normalize_to(to: str) -> str:
    """Ensure the number has the whatsapp: prefix."""
    if to.startswith("whatsapp:"):
        return to
    return f"whatsapp:{to}"


def _from_kwargs() -> dict:
    """Return either messaging_service_sid or from_, whichever is configured."""
    if config.TWILIO_MESSAGING_SERVICE_SID:
        return {"messaging_service_sid": config.TWILIO_MESSAGING_SERVICE_SID}
    return {"from_": config.TWILIO_WHATSAPP_FROM}


# ── Public API ─────────────────────────────────────────────────────────────

def send_message(body: str, to: Optional[str] = None) -> str:
    """Send a single WhatsApp message via Twilio. Returns the message SID.

    Tries Content Template first (if TWILIO_CONTENT_SID is configured),
    then falls back to a plain freeform body.
    """
    client = _get_client()
    to_num = _normalize_to(to or config.WHATSAPP_TO)
    base   = {"to": to_num, **_from_kwargs()}

    # ── Mode 1: Content Template ───────────────────────────────────────────
    if config.TWILIO_CONTENT_SID:
        try:
            msg = client.messages.create(
                **base,
                content_sid=config.TWILIO_CONTENT_SID,
                # Pass the full text as variable {{1}} of the template.
                content_variables=json.dumps({"1": body}),
            )
            log.debug("Sent via Content Template — SID %s", msg.sid)
            return msg.sid
        except Exception as exc:
            log.warning(
                "Content Template send failed (%s) — falling back to freeform.", exc
            )

    # ── Mode 2: Freeform body (Sandbox / 24-hour window) ──────────────────
    msg = client.messages.create(**base, body=body)
    log.debug("Sent as freeform body — SID %s", msg.sid)
    return msg.sid


async def send_all(messages: list[str], to: Optional[str] = None) -> list[str]:
    """Send multiple messages. Returns list of SIDs.
    Runs in executor since Twilio SDK is synchronous.
    """
    loop = asyncio.get_event_loop()
    sids = []
    for body in messages:
        sid = await loop.run_in_executor(None, send_message, body, to)
        sids.append(sid)
        await asyncio.sleep(0.5)   # small delay between messages
    return sids
