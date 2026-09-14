"""Market snapshot for the newsletter — S&P/Nasdaq/Dow/VIX/10Y/DXY/USD-ILS.

Uses Yahoo Finance's unofficial chart endpoint (no API key required). Each
symbol is fetched independently and failures don't block the others — same
per-source isolation pattern as feeds.py — so one broken symbol never keeps
the newsletter from going out.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp

_SYMBOLS = [
    ("S&P 500",   "^GSPC"),
    ("Nasdaq",    "^IXIC"),
    ("Dow Jones", "^DJI"),
    ("VIX",       "^VIX"),
    ("US 10Y",    "^TNX"),      # already expressed as a yield percentage
    ("DXY",       "DX-Y.NYB"),
    ("USD/ILS",   "ILS=X"),
]

_URL     = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketBot/1.0)"}


@dataclass
class Quote:
    name:       str
    price:      float | None
    change_pct: float | None
    ok:         bool
    error:      str = ""


async def _fetch_one(session: aiohttp.ClientSession, name: str, symbol: str) -> Quote:
    try:
        async with session.get(_URL.format(symbol=symbol)) as resp:
            resp.raise_for_status()
            data = await resp.json()
        meta       = data["chart"]["result"][0]["meta"]
        price      = meta["regularMarketPrice"]
        change_pct = meta.get("regularMarketChangePercent")
        return Quote(name=name, price=price, change_pct=change_pct, ok=True)
    except Exception as exc:
        return Quote(name=name, price=None, change_pct=None, ok=False, error=str(exc))


async def fetch_snapshot() -> list[Quote]:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, headers=_HEADERS) as session:
        tasks = [_fetch_one(session, name, symbol) for name, symbol in _SYMBOLS]
        return list(await asyncio.gather(*tasks))


def format_snapshot_for_prompt(quotes: list[Quote]) -> str:
    """Plain-text lines for the Claude prompt — not the final HTML."""
    lines = []
    for q in quotes:
        if q.ok and q.price is not None:
            sign = "+" if (q.change_pct or 0) >= 0 else ""
            pct  = f" ({sign}{q.change_pct:.2f}%)" if q.change_pct is not None else ""
            lines.append(f"{q.name}: {q.price:,.2f}{pct}")
        else:
            lines.append(f"{q.name}: לא זמין ({q.error[:80]})")
    return "\n".join(lines)
