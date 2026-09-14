"""Recent headlines for the "house stocks" watchlist (config.WATCHLIST_STOCKS),
for the morning brief's dedicated section. Uses Yahoo Finance's unofficial
search/news endpoint (no API key) — same approach as market_data.py. Claude
decides what's actually significant when composing the brief; this module
just gathers raw headlines per ticker, filtering isn't done here.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import aiohttp

_URL     = "https://query2.finance.yahoo.com/v1/finance/search?q={symbol}&newsCount=6&quotesCount=0"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketBot/1.0)"}


@dataclass
class TickerNews:
    symbol:    str
    name:      str
    headlines: list[str] = field(default_factory=list)
    ok:        bool = True
    error:     str = ""


async def _fetch_one(session: aiohttp.ClientSession, symbol: str, name: str) -> TickerNews:
    try:
        async with session.get(_URL.format(symbol=symbol)) as resp:
            resp.raise_for_status()
            data = await resp.json()
        headlines = [
            f"{item.get('title', '')} ({item.get('publisher', '')})"
            for item in data.get("news", [])
            if item.get("title")
        ]
        return TickerNews(symbol=symbol, name=name, headlines=headlines)
    except Exception as exc:
        return TickerNews(symbol=symbol, name=name, ok=False, error=str(exc))


async def fetch_watchlist_news(watchlist: list[dict]) -> list[TickerNews]:
    if not watchlist:
        return []
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, headers=_HEADERS) as session:
        tasks = [_fetch_one(session, w["symbol"], w.get("name", w["symbol"])) for w in watchlist]
        return list(await asyncio.gather(*tasks))


def format_watchlist_for_prompt(items: list[TickerNews]) -> str:
    if not items:
        return "(אין רשימת מניות בית מוגדרת — דלג על הסעיף הזה)"
    lines = []
    for t in items:
        if not t.ok:
            lines.append(f"- {t.name} ({t.symbol}): שגיאה בשליפת חדשות ({t.error[:60]})")
            continue
        if not t.headlines:
            lines.append(f"- {t.name} ({t.symbol}): אין כותרות חדשות זמינות")
            continue
        lines.append(f"- {t.name} ({t.symbol}):")
        for h in t.headlines:
            lines.append(f"    · {h}")
    return "\n".join(lines)
