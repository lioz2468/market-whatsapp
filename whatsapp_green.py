"""WhatsApp sender — Green API provider (supports groups)."""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import aiohttp

import config


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
    return (
        f"https://api.green-api.com"
        f"/waInstance{config.GREEN_API_INSTANCE}"
    )


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
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()
    finally:
        if close_session:
            await session.close()


async def send_all(messages: list[str], to: Optional[str] = None) -> list[dict]:
    """Send multiple messages. Returns list of API responses."""
    responses = []
    timeout   = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for body in messages:
            result = await send_message(body, to=to, session=session)
            responses.append(result)
            await asyncio.sleep(0.8)   # Green API recommends short delays

    return responses
