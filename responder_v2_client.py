"""Responder (רב מסר) REST API V2.0 client — OAuth2 client_credentials + lists.

Docs: https://app.swaggerhub.com/apis/Responder/responder/V2.0
  base URL:  https://graph.responder.live/v2
  auth:      POST /oauth/token  {grant_type, scope, client_id, client_secret, user_token}
             → {access_token, ...}, used as `Authorization: Bearer <token>`

This is a DIFFERENT API from responder_client.py (V1): confirmed against the
official spec, V2.0 covers only lists/subscribers/tags/webhooks — it has no
message create/test/send endpoint. It exists here only so RESPONDER_LIST_ID
and credentials can be verified without waiting on a support call for V1
message-sending credentials. See config.py's Responder section for details.
"""
from __future__ import annotations

from typing import Optional

import aiohttp

import config


class ResponderV2Error(RuntimeError):
    """Raised on a non-2xx response from the V2 API."""


async def _request(
    method: str, path: str,
    token: Optional[str] = None,
    json_body: Optional[dict] = None,
) -> dict:
    url     = f"{config.RESPONDER_V2_BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, headers=headers, json=json_body) as resp:
            text = await resp.text()
            try:
                payload = await resp.json(content_type=None)
            except Exception:
                raise ResponderV2Error(f"{method} {path} → HTTP {resp.status}, non-JSON body: {text[:300]}")
            if resp.status >= 400:
                raise ResponderV2Error(f"{method} {path} → HTTP {resp.status}: {payload}")
            return payload


async def get_access_token() -> str:
    """POST /oauth/token — exchange Client ID/Secret + User Token for a Bearer token."""
    config.validate_responder_v2()

    client_id: str | int = config.RESPONDER_V2_CLIENT_ID
    if client_id.isdigit():
        client_id = int(client_id)

    body = {
        "grant_type":    "client_credentials",
        "scope":         "*",
        "client_id":     client_id,
        "client_secret": config.RESPONDER_V2_CLIENT_SECRET,
        "user_token":    config.RESPONDER_V2_USER_TOKEN,
    }
    payload = await _request("POST", "/oauth/token", json_body=body)
    token = payload.get("access_token")
    if not token:
        raise ResponderV2Error(f"POST /oauth/token — no access_token in response: {payload}")
    return token


async def get_lists() -> list[dict]:
    """GET /lists — authenticates first, then returns the account's lists."""
    token = await get_access_token()
    payload = await _request("GET", "/lists", token=token)
    # The exact response envelope isn't nailed down from the spec excerpt —
    # handle both a bare list and a {"data": [...]} / {"lists": [...]} wrapper.
    if isinstance(payload, list):
        return payload
    return payload.get("data") or payload.get("lists") or payload.get("LISTS") or []
