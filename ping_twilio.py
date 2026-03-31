"""ping_twilio.py — Keep the Twilio 24-hour service window open.

WhatsApp Business API allows free-form replies only within 24 hours of the
last user-initiated message. This script sends a short ping FROM your WhatsApp
(via Green API) TO the Twilio number, resetting the window.

Run it once every ~20 hours (before the 24h window expires):

    python ping_twilio.py

Or add to GitHub Actions as a scheduled step that runs before the bot.

Prerequisites:
  - GREEN_API_INSTANCE and GREEN_API_TOKEN must be set in .env
  - TWILIO_WHATSAPP_FROM must be the Twilio number to ping (e.g. +14155238886)
"""

import asyncio
import os
import re
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv()

GREEN_API_INSTANCE = os.getenv("GREEN_API_INSTANCE", "")
GREEN_API_TOKEN    = os.getenv("GREEN_API_TOKEN", "")
TWILIO_NUMBER      = os.getenv("TWILIO_WHATSAPP_FROM", "").replace("whatsapp:", "")
PING_TEXT          = os.getenv("PING_TEXT", ".")   # single dot — invisible but valid


def _to_chat_id(number: str) -> str:
    """Convert +14155238886 → 14155238886@c.us"""
    digits = re.sub(r"\D", "", number)
    return f"{digits}@c.us"


async def ping() -> bool:
    if not all([GREEN_API_INSTANCE, GREEN_API_TOKEN, TWILIO_NUMBER]):
        print("ERROR: Missing GREEN_API_INSTANCE, GREEN_API_TOKEN or TWILIO_WHATSAPP_FROM in .env")
        return False

    chat_id = _to_chat_id(TWILIO_NUMBER)
    url     = (
        f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE}"
        f"/sendMessage/{GREEN_API_TOKEN}"
    )
    payload = {"chatId": chat_id, "message": PING_TEXT}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            if resp.status == 200 and data.get("idMessage"):
                print(f"Ping sent to {TWILIO_NUMBER} — message ID: {data['idMessage']}")
                print("24-hour Twilio window is now open (or refreshed).")
                return True
            else:
                print(f"Ping failed: {resp.status} — {data}")
                return False


if __name__ == "__main__":
    ok = asyncio.run(ping())
    sys.exit(0 if ok else 1)
