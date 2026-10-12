"""WhatsApp sender — Green API provider (supports groups)."""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import aiohttp

import config


class GreenAPIError(RuntimeError):
    """Raised when Green API fails. Deliberately not an OSError so callers'
    `except EnvironmentError` (config errors) doesn't swallow it."""


# ── Chat ID helpers ────────────────────────────────────────────────────────

def _to_chat_id(to: str) -> str:
    """
    Convert a phone number or group ID to Green API chatId format.

    Individual: +972501234567  →  972501234567@c.us
    Group:      972501234567-1234567890@g.us  →  unchanged
    """
    if "@" in to:
        return to   # already a chatId (individual @c.us or group @g.us)

    # Strip non-digits
    digits = re.sub(r"\D", "", to)
    return f"{digits}@c.us"


def _base_url() -> str:
    host = config.GREEN_API_URL.rstrip("/")
    if not host:
        # Instance-specific host: first 4 digits of the instance ID
        host = f"https://{str(config.GREEN_API_INSTANCE)[:4]}.api.greenapi.com"
    return f"{host}/waInstance{config.GREEN_API_INSTANCE}"


# ── Public API ─────────────────────────────────────────────────────────────

async def send_message(
    body: str,
    to: Optional[str] = None,
    session: Optional[aiohttp.ClientSession] = None,
) -> dict:
    """
    Send a WhatsApp message via Green API.
    Works for both individual chats and groups.
    Returns the API response dict.
    """
    chat_id = _to_chat_id(to or config.WHATSAPP_TO)
    url     = f"{_base_url()}/sendMessage/{config.GREEN_API_TOKEN}"
    payload = {"chatId": chat_id, "message": body}

    close_session = session is None
    if session is None:
        session = aiohttp.ClientSession()

    try:
        # Retry only connection failures (request never reached Green API) —
        # a timeout after the request was sent may already have delivered it.
        for attempt in range(3):
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise GreenAPIError(f"Green API HTTP {resp.status}: {text[:300]}")
                    return await resp.json()
            except aiohttp.ClientConnectionError as exc:
                if attempt == 2:
                    raise GreenAPIError(f"Green API connection failed: {exc!r}") from exc
                await asyncio.sleep(5 * (attempt + 1))
            except asyncio.TimeoutError as exc:
                raise GreenAPIError(
                    "Green API sendMessage timed out (no response within "
                    f"{session.timeout.total}s) — check the instance in the Green API console"
                ) from exc
    finally:
        if close_session:
            await session.close()


async def get_state(session: aiohttp.ClientSession) -> str:
    """Return the instance state (e.g. 'authorized', 'notAuthorized', 'starting')."""
    url = f"{_base_url()}/getStateInstance/{config.GREEN_API_TOKEN}"
    try:
        async with session.get(url) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise GreenAPIError(f"Green API getStateInstance HTTP {resp.status}: {text[:300]}")
            data = await resp.json()
    except asyncio.TimeoutError as exc:
        raise GreenAPIError("Green API getStateInstance timed out") from exc
    except aiohttp.ClientConnectionError as exc:
        raise GreenAPIError(f"Green API connection failed: {exc!r}") from exc
    return data.get("stateInstance", "?")


async def send_all(messages: list[str], to: Optional[str] = None) -> list[dict]:
    """Send multiple messages. Returns list of API responses."""
    responses = []
    timeout   = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        state = await get_state(session)
        if state != "authorized":
            raise GreenAPIError(
                f"Green API instance state is '{state}', not 'authorized' — "
                "re-scan the QR code in the Green API console"
            )
        for body in messages:
            result = await send_message(body, to=to, session=session)
            responses.append(result)
            await asyncio.sleep(0.8)   # Green API recommends short delays

    return responses
