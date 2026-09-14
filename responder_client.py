"""Responder (רב מסר) REST API client — auth signing + message create/test/send.

Docs: https://github.com/responder/restapi
  (Authentication/README.md, Messages/README.md, Lists/README.md)

Auth is a signed header, not a plain API key:
  Authorization: c_key=...,c_secret=...,u_key=...,u_secret=...,nonce=...,timestamp=...
where c_secret = md5(RESPONDER_C_SECRET + nonce), u_secret = md5(RESPONDER_U_SECRET + nonce),
nonce is random per request, and every value is url-encoded.

Entirely separate from the WhatsApp send path (whatsapp_twilio.py / whatsapp_green.py) —
used only by send_newsletter.py.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import urllib.parse
from typing import Optional

import aiohttp

import config

BASE_URL = "https://api.responder.co.il/main"


class ResponderError(RuntimeError):
    """Raised on a non-2xx response, an ERRORS[] payload, or a reported failure."""


def _auth_header() -> str:
    nonce     = secrets.token_hex(16)
    timestamp = str(int(time.time()))
    c_secret  = hashlib.md5((config.RESPONDER_C_SECRET + nonce).encode("utf-8")).hexdigest()
    u_secret  = hashlib.md5((config.RESPONDER_U_SECRET + nonce).encode("utf-8")).hexdigest()

    params = {
        "c_key":     config.RESPONDER_C_KEY,
        "c_secret":  c_secret,
        "u_key":     config.RESPONDER_U_KEY,
        "u_secret":  u_secret,
        "nonce":     nonce,
        "timestamp": timestamp,
    }
    return ",".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())


async def _request(method: str, path: str, data: Optional[dict] = None) -> dict:
    config.validate_responder()
    url     = f"{BASE_URL}{path}"
    headers = {"Authorization": _auth_header()}

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, headers=headers, data=data) as resp:
            text = await resp.text()
            try:
                payload = json.loads(text)
            except ValueError:
                raise ResponderError(f"{method} {path} → HTTP {resp.status}, non-JSON body: {text[:300]}")
            if resp.status >= 400:
                raise ResponderError(f"{method} {path} → HTTP {resp.status}: {payload}")
            errors = payload.get("ERRORS")
            if errors:
                raise ResponderError(f"{method} {path} → API errors: {errors}")
            return payload


# ── Public API ─────────────────────────────────────────────────────────────

async def get_lists(limit: int = 500) -> list[dict]:
    """GET /main/lists — each item has ID / NAME / DESCRIPTION."""
    payload = await _request("GET", f"/lists?limit={limit}")
    return payload.get("LISTS", [])


async def create_message(list_id: str, subject: str, html_body: str, language: str = "hebrew") -> int:
    """POST /main/lists/{listId}/messages — returns the new MESSAGE_ID."""
    info = {
        "TYPE":        "1",
        "BODY_TYPE":   "0",
        "SUBJECT":     subject,
        "BODY":        html_body,
        "LANGUAGE":    language,
        "CHECK_LINKS": "1",
    }
    payload = await _request(
        "POST", f"/lists/{list_id}/messages",
        data={"info": json.dumps(info, ensure_ascii=False)},
    )
    return payload["MESSAGE_ID"]


async def send_test(list_id: str, message_id: int, name: str, email: str, phone: str = "") -> bool:
    """POST /main/lists/{listId}/messages/{messageId}/test — sends to one address only."""
    data = {"name": name, "email": email, "phone": phone}
    payload = await _request(
        "POST", f"/lists/{list_id}/messages/{message_id}/test",
        data={"data": json.dumps(data, ensure_ascii=False)},
    )
    return bool(payload.get("status"))


async def send_live(list_id: str, message_id: int) -> bool:
    """POST /main/lists/{listId}/messages/{messageId} — sends to the whole list. No undo."""
    payload = await _request("POST", f"/lists/{list_id}/messages/{message_id}")
    return bool(payload.get("MESSAGE_SENT"))
