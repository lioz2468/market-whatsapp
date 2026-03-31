"""Async RSS feed fetching + Article model + deduplication."""
from __future__ import annotations

import asyncio
import hashlib
import html
import re
from dataclasses import dataclass
from typing import Optional

import aiohttp
import feedparser

import config


# ── Article model ──────────────────────────────────────────────────────────

@dataclass
class Article:
    title:     str
    url:       str
    summary:   str
    published: str
    source:    str
    lang:      str   # "he" | "en"
    hash:      str   # dedup key

    @classmethod
    def from_entry(cls, entry: dict, source_name: str, lang: str) -> "Article":
        title   = _clean(entry.get("title", ""))
        url     = entry.get("link", "")
        summary = _clean(entry.get("summary", entry.get("description", "")))[:800]
        pub     = entry.get("published", entry.get("updated", ""))
        return cls(
            title=title,
            url=url,
            summary=summary,
            published=pub,
            source=source_name,
            lang=lang,
            hash=_hash(title),
        )


# ── Public entry point ─────────────────────────────────────────────────────

async def fetch_all() -> list[Article]:
    """Fetch all RSS feeds concurrently. Returns deduplicated Article list."""
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MarketBot/1.0)"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        tasks = [_fetch_feed(session, feed) for feed in config.RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    articles: list[Article] = []
    seen_hashes: set[str] = set()

    for feed_articles in results:
        if isinstance(feed_articles, Exception):
            continue
        for article in feed_articles:
            if article.hash not in seen_hashes and article.title:
                seen_hashes.add(article.hash)
                articles.append(article)

    return articles


# ── Per-feed fetch ─────────────────────────────────────────────────────────

async def _fetch_feed(
    session: aiohttp.ClientSession,
    feed_info: dict,
) -> list[Article]:
    name          = feed_info["name"]
    lang          = feed_info["lang"]
    # Support fallback_urls for mirrors (e.g. Nitter instances)
    urls_to_try   = [feed_info["url"]] + feed_info.get("fallback_urls", [])

    content: Optional[bytes] = None
    used_url = urls_to_try[0]

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
        print(f"  [feeds] ⚠ Could not fetch '{name}' (tried {len(urls_to_try)} URL(s))")
        return []

    # Strip UTF-8 BOM if present — some Hebrew sites prepend it before <?xml>,
    # which causes "XML or text declaration not at start of entity" in expat.
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]

    # feedparser is CPU-bound but fast; run in default executor
    loop   = asyncio.get_event_loop()
    parsed = await loop.run_in_executor(None, feedparser.parse, content)

    # If bytes parsing failed, retry by letting feedparser fetch the URL itself
    # (works around intermittent encoding issues from some Hebrew news servers).
    if parsed.bozo and not parsed.entries:
        parsed = await loop.run_in_executor(None, feedparser.parse, used_url)

    if parsed.bozo and not parsed.entries:
        print(f"  [feeds] ⚠ Parse error for '{name}': {parsed.bozo_exception}")
        return []

    articles = []
    for entry in parsed.entries[:15]:          # limit per feed
        article = Article.from_entry(entry, name, lang)
        if article.title:
            articles.append(article)

    print(f"  [feeds] {name}: {len(articles)} article(s)")
    return articles


# ── Helpers ────────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")

def _clean(text: str) -> str:
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    return " ".join(text.split())


def _hash(title: str) -> str:
    return hashlib.md5(title.strip().lower().encode()).hexdigest()[:16]
