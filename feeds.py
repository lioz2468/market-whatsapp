"""Async RSS feed fetching + Article model + deduplication + pre-filtering."""
from __future__ import annotations

import asyncio
import hashlib
import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp
import feedparser

import config


# ── Article model ──────────────────────────────────────────────────────────

@dataclass
class Article:
    title:        str
    url:          str
    summary:      str
    published:    str
    source:       str
    lang:         str            # "he" | "en"
    hash:         str            # dedup key
    published_dt: Optional[datetime] = field(default=None, repr=False)

    @classmethod
    def from_entry(cls, entry: dict, source_name: str, lang: str) -> "Article":
        title   = _clean(entry.get("title", ""))
        url     = entry.get("link", "")
        summary = _clean(entry.get("summary", entry.get("description", "")))[:800]
        pub     = entry.get("published", entry.get("updated", ""))

        # Parse publish datetime for age-based pre-filtering
        pub_dt: Optional[datetime] = None
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed_time:
            try:
                pub_dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
            except Exception:
                pass

        return cls(
            title=title,
            url=url,
            summary=summary,
            published=pub,
            source=source_name,
            lang=lang,
            hash=_hash(title),
            published_dt=pub_dt,
        )


# ── Feed status ────────────────────────────────────────────────────────────

@dataclass
class FeedStatus:
    name:    str
    count:   int          # articles fetched (0 on error)
    ok:      bool
    error:   str = ""


# ── Public entry points ────────────────────────────────────────────────────

async def fetch_all() -> tuple[list[Article], list[FeedStatus]]:
    """Fetch all RSS feeds concurrently.

    Returns (deduplicated articles, per-feed status list).
    """
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MarketBot/1.0)"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        tasks = [_fetch_feed(session, feed) for feed in config.RSS_FEEDS]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    articles:   list[Article]    = []
    statuses:   list[FeedStatus] = []
    seen_hashes: set[str]        = set()

    for i, result in enumerate(raw_results):
        feed_name = config.RSS_FEEDS[i]["name"]
        if isinstance(result, Exception):
            statuses.append(FeedStatus(name=feed_name, count=0, ok=False,
                                       error=str(result)))
            continue
        feed_articles, status = result
        statuses.append(status)
        for article in feed_articles:
            if article.hash not in seen_hashes and article.title:
                seen_hashes.add(article.hash)
                articles.append(article)

    # Print feed summary
    working = sum(1 for s in statuses if s.ok)
    total   = len(statuses)
    print(f"  Working feeds: {working}/{total} | Total articles: {len(articles)}")

    return articles, statuses


async def check_feeds() -> list[FeedStatus]:
    """Fetch all feeds and report status — no filtering, no Claude."""
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MarketBot/1.0)"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        tasks = [_fetch_feed(session, feed) for feed in config.RSS_FEEDS]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    statuses: list[FeedStatus] = []
    for i, result in enumerate(raw_results):
        feed_name = config.RSS_FEEDS[i]["name"]
        if isinstance(result, Exception):
            statuses.append(FeedStatus(name=feed_name, count=0, ok=False,
                                       error=str(result)))
        else:
            _, status = result
            statuses.append(status)
    return statuses


# ── Pre-filter (saves Claude API calls) ───────────────────────────────────

# Patterns that signal non-financial content — filtered before any API call.
_SKIP_EN = re.compile(
    r"\b("
    r"recipe|cooking|chef|restaurant review|fashion|beauty|makeup|skincare"
    r"|celebrity|actor|actress|singer|musician|movie review|film review"
    r"|box office|oscar|grammy|emmy|billboard|album|concert|tour"
    r"|nfl|nba|mlb|nhl|mls|fifa|uefa|premier league|la liga"
    r"|touchdown|home run|slam dunk|hat.?trick|playoff|championship game"
    r"|horoscope|astrology|zodiac"
    r")\b",
    re.I,
)
_SKIP_HE = re.compile(
    r"(מתכון|בישול|אופנה|יופי|כדורגל|כדורסל|קולנוע|סרט חדש|מוזיקה|הופעה|אסטרולוגיה|הורוסקופ)",
)


def pre_filter(
    articles: list[Article],
    max_age_hours: int = 48,
) -> tuple[list[Article], int]:
    """Filter out irrelevant articles before sending to Claude.

    Returns (kept_articles, skipped_count).
    Removes:
      - Articles older than max_age_hours
      - Articles matching non-financial keyword patterns
    """
    now     = datetime.now(timezone.utc)
    cutoff  = now - timedelta(hours=max_age_hours)
    kept    = []
    skipped = 0

    for a in articles:
        # Age filter
        if a.published_dt and a.published_dt < cutoff:
            skipped += 1
            continue

        # Keyword filter
        pattern = _SKIP_EN if a.lang == "en" else _SKIP_HE
        if pattern.search(a.title):
            skipped += 1
            continue

        kept.append(a)

    return kept, skipped


# ── Per-feed fetch ─────────────────────────────────────────────────────────

async def _fetch_feed(
    session:   aiohttp.ClientSession,
    feed_info: dict,
) -> tuple[list[Article], FeedStatus]:
    name        = feed_info["name"]
    lang        = feed_info["lang"]
    urls_to_try = [feed_info["url"]] + feed_info.get("fallback_urls", [])

    content:  Optional[bytes] = None
    used_url  = urls_to_try[0]

    for url in urls_to_try:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    content  = await resp.read()
                    used_url = url
                    break
        except Exception:
            pass

    if content is None:
        err = f"Could not fetch (tried {len(urls_to_try)} URL(s))"
        print(f"  [feeds] ✗ {name}: {err}")
        return [], FeedStatus(name=name, count=0, ok=False, error=err)

    # Strip UTF-8 BOM
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]

    loop   = asyncio.get_event_loop()
    parsed = await loop.run_in_executor(None, feedparser.parse, content)

    # Retry via URL if bytes parse failed
    if parsed.bozo and not parsed.entries:
        parsed = await loop.run_in_executor(None, feedparser.parse, used_url)

    if parsed.bozo and not parsed.entries:
        err = str(parsed.bozo_exception)
        print(f"  [feeds] ✗ {name}: {err}")
        return [], FeedStatus(name=name, count=0, ok=False, error=err)

    articles = []
    for entry in parsed.entries[:15]:
        article = Article.from_entry(entry, name, lang)
        if article.title:
            articles.append(article)

    print(f"  [feeds] {name}: {len(articles)} article(s)")
    return articles, FeedStatus(name=name, count=len(articles), ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    return " ".join(text.split())


def _hash(title: str) -> str:
    return hashlib.md5(title.strip().lower().encode()).hexdigest()[:16]
