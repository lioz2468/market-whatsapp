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
    r"|celebrity|celeb|actor|actress|singer|musician|movie review|film review"
    r"|box office|oscar|grammy|emmy|billboard|album|concert|tour"
    r"|nfl|nba|mlb|nhl|mls|fifa|uefa|premier league|la liga|bundesliga"
    r"|touchdown|home run|slam dunk|hat.?trick|playoff|championship game"
    r"|horoscope|astrology|zodiac"
    r"|lifestyle|wellness|diet|weight loss|fitness tip|workout"
    r"|entertainment|gossip|dating|relationship advice|parenting tip"
    r"|sport(s)? score|game recap|match result|transfer rumor"
    r")\b",
    re.I,
)
_SKIP_HE = re.compile(
    r"(מתכון|בישול|שף|מסעדה|אופנה|יופי|כדורגל|כדורסל|קולנוע|סרט חדש"
    r"|מוזיקה|הופעה|אסטרולוגיה|הורוסקופ|ספורט|ליגה|טורניר|גביע"
    r"|דיאטה|כושר|אורח.?חיים|רכילות|זוגיות|הורות)",
)

# Stop-words ignored when comparing titles for near-duplicate detection
_TITLE_STOP = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
    "was", "were", "will", "be", "as", "by", "with", "from", "that",
})


def _title_words(title: str) -> frozenset[str]:
    return frozenset(
        w.lower() for w in re.split(r"\W+", title)
        if len(w) > 3 and w.lower() not in _TITLE_STOP
    )


def pre_filter(
    articles: list[Article],
    max_age_hours: int = 12,
    sent_titles: list[str] | None = None,
) -> tuple[list[Article], int]:
    """Filter out irrelevant articles before sending to Claude.

    Returns (kept_articles, skipped_count).
    Removes:
      - Articles older than max_age_hours (default 12h)
      - Articles with fewer than 20 words in title+summary
      - Articles matching non-financial keyword patterns
      - Articles whose titles are ≥65% similar to a recently-sent title
    """
    now     = datetime.now(timezone.utc)
    cutoff  = now - timedelta(hours=max_age_hours)
    kept    = []
    skipped = 0

    sent_word_sets: list[frozenset[str]] = (
        [_title_words(t) for t in sent_titles] if sent_titles else []
    )

    for a in articles:
        # Age filter
        if a.published_dt and a.published_dt < cutoff:
            skipped += 1
            continue

        # Minimum content length (title + summary must have ≥20 words)
        word_count = len(a.title.split()) + len(a.summary.split())
        if word_count < 20:
            skipped += 1
            continue

        # Keyword filter
        pattern = _SKIP_EN if a.lang == "en" else _SKIP_HE
        if pattern.search(a.title):
            skipped += 1
            continue

        # Near-duplicate title check against recently-sent articles
        if sent_word_sets:
            article_words = _title_words(a.title)
            if len(article_words) >= 3:
                for sent_words in sent_word_sets:
                    if not sent_words:
                        continue
                    overlap = len(article_words & sent_words) / min(len(article_words), len(sent_words))
                    if overlap >= 0.65:
                        skipped += 1
                        break
                else:
                    kept.append(a)
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
