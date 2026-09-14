"""Recent headlines for the "house stocks" watchlist (config.WATCHLIST_STOCKS),
for the morning brief's dedicated section. Uses Yahoo Finance's unofficial
search/news endpoint (no API key) — same approach as market_data.py. Claude
decides what's actually significant when composing the brief; this module
gathers raw headlines per ticker and filters out anything older than
_MAX_AGE_HOURS — old evergreen "Motley Fool"-style content otherwise
crowds out anything genuinely new.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp

_URL     = "https://query2.finance.yahoo.com/v1/finance/search?q={symbol}&newsCount=10&quotesCount=0"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketBot/1.0)"}

# Only headlines published within this window are considered — the rest of
# Yahoo's results skew toward evergreen listicle content, not real news.
_MAX_AGE_HOURS = 48


@dataclass
class Headline:
    title:     str
    publisher: str
    published: datetime


@dataclass
class TickerNews:
    symbol:    str
    name:      str
    headlines: list[Headline] = field(default_factory=list)
    ok:        bool = True
    error:     str = ""


async def _fetch_one(session: aiohttp.ClientSession, symbol: str, name: str) -> TickerNews:
    try:
        async with session.get(_URL.format(symbol=symbol)) as resp:
            resp.raise_for_status()
            data = await resp.json()

        cutoff = time.time() - _MAX_AGE_HOURS * 3600
        headlines = [
            Headline(
                title=item["title"],
                publisher=item.get("publisher", ""),
                published=datetime.fromtimestamp(item["providerPublishTime"], tz=timezone.utc),
            )
            for item in data.get("news", [])
            if item.get("title") and item.get("providerPublishTime", 0) >= cutoff
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

    now = datetime.now(timezone.utc)
    lines = [f"(רק כותרות מ-{_MAX_AGE_HOURS} השעות האחרונות — כל השאר כבר סונן)"]
    for t in items:
        if not t.ok:
            lines.append(f"- {t.name} ({t.symbol}): שגיאה בשליפת חדשות ({t.error[:60]})")
            continue
        if not t.headlines:
            lines.append(f"- {t.name} ({t.symbol}): אין כותרות חדשות מה-{_MAX_AGE_HOURS} שעות האחרונות")
            continue
        lines.append(f"- {t.name} ({t.symbol}):")
        for h in t.headlines:
            age_hours = round((now - h.published).total_seconds() / 3600)
            lines.append(f"    · [{age_hours}ש לפני] {h.title} ({h.publisher})")
    return "\n".join(lines)
