"""Central configuration — loaded once at import time."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR           = Path(__file__).parent
SENT_LOG_PATH      = BASE_DIR / "sent_log.json"
PENDING_PATH       = BASE_DIR / "pending_articles.json"
# style_profile.json lives in the sibling style-extractor project
STYLE_PROFILE_PATH = BASE_DIR.parent / "style-extractor" / "style_profile.json"

# ── Claude ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY        = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL             = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_CLASSIFIER_MODEL  = os.getenv("CLAUDE_CLASSIFIER_MODEL", "claude-haiku-4-5-20251001")
CLASSIFIER_BATCH_SIZE    = int(os.getenv("CLASSIFIER_BATCH_SIZE", "12"))
MAX_CONCURRENT_CLAUDE    = int(os.getenv("MAX_CONCURRENT_CLAUDE", "3"))

# ── WhatsApp (shared) ──────────────────────────────────────────────────────
WHATSAPP_TO      = os.getenv("WHATSAPP_TO", "")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "green")

# Separate target for the morning brief group (send_morning_brief.py) — a
# dedicated WhatsApp group for "בריף בוקר" subscribers, distinct from
# WHATSAPP_TO (the main per-article bot's target). Falls back to WHATSAPP_TO
# if unset, so a single-target setup still works without extra config.
MORNING_BRIEF_TO = os.getenv("MORNING_BRIEF_TO", "") or WHATSAPP_TO

# ── Twilio ─────────────────────────────────────────────────────────────────
TWILIO_SID                   = os.getenv("TWILIO_SID", "")
TWILIO_AUTH_TOKEN            = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM         = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
# Optional: Twilio Content API template SID (HX...) for outbound sessions.
# If set, the bot sends via template (required for production WhatsApp Business).
# The template should have a single body variable {{1}} that receives the full message.
TWILIO_CONTENT_SID           = os.getenv("TWILIO_CONTENT_SID", "")
# Optional: Messaging Service SID (MG...) — alternative to TWILIO_WHATSAPP_FROM.
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")

# ── Green API ──────────────────────────────────────────────────────────────
GREEN_API_INSTANCE = os.getenv("GREEN_API_INSTANCE", "")
GREEN_API_TOKEN    = os.getenv("GREEN_API_TOKEN", "")

# ── X (Twitter) API v2 ─────────────────────────────────────────────────────
# Feed source for @wallstengine, replacing the now-dead Nitter RSS mirrors.
# If unset, the Twitter feed is skipped silently (see feeds_twitter.py).
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")

# ── Filter settings ────────────────────────────────────────────────────────
MIN_IMPORTANCE_SCORE     = int(os.getenv("MIN_IMPORTANCE_SCORE", "6"))
MAX_ARTICLES_PER_RUN     = int(os.getenv("MAX_ARTICLES_PER_RUN", "5"))
DIGEST_HOURS             = int(os.getenv("DIGEST_HOURS", "12"))

# How far back topic_dedup_filter() looks when deciding whether a "new"
# article is really just a restatement of something already sent (e.g.
# "bond yields near 5%" sent 3 days apart with the same framing). Used to be
# hardcoded to 18h, which meant anything sent >18h ago wasn't shown to the
# dedup check at all — slow-moving macro topics (rates, yields, inflation
# prints) routinely resurface 2-4 days apart and sailed straight through.
TOPIC_DEDUP_HOURS        = int(os.getenv("TOPIC_DEDUP_HOURS", "96"))

# ── Email digest pool (separate pipeline — does not affect WhatsApp sending) ─
# Populates email_digest.json once/day for the morning email, by combining:
#   (a) world-news articles fetched from WORLD_RSS_FEEDS and classified here, and
#   (b) business/tech articles already approved for WhatsApp in the last
#       EMAIL_LOOKBACK_HOURS (read straight from sent_log.json — no extra
#       Claude calls needed for those).
# Entirely additive: does not read or modify RSS_FEEDS, MIN_IMPORTANCE_SCORE,
# or anything the WhatsApp send path depends on.
EMAIL_DIGEST_PATH         = BASE_DIR / "email_digest.json"
EMAIL_LOOKBACK_HOURS      = int(os.getenv("EMAIL_LOOKBACK_HOURS", "24"))
MIN_WORLD_IMPORTANCE_SCORE = int(os.getenv("MIN_WORLD_IMPORTANCE_SCORE", "5"))
MAX_WORLD_ARTICLES        = int(os.getenv("MAX_WORLD_ARTICLES", "10"))
# "business" is still reused free from sent_log.json's WhatsApp-approved
# articles. "tech" used to be split out of that same reuse (by source name)
# but almost never had anything — nearly nothing tech-related clears the
# WhatsApp bot's 15-criteria filter. It now has its own dedicated feeds +
# classifier below (TECH_RSS_FEEDS / email_tech_classifier.py), same pattern
# as world news.
MIN_TECH_IMPORTANCE_SCORE = int(os.getenv("MIN_TECH_IMPORTANCE_SCORE", "5"))
MAX_TECH_ARTICLES         = int(os.getenv("MAX_TECH_ARTICLES", "8"))

# Minimum minutes between consecutive *scheduled* runs (see the
# min-gap guard in main.py's run()). Manual workflow_dispatch / local runs
# never check or affect this.
MIN_SEND_INTERVAL_MINUTES = int(os.getenv("MIN_SEND_INTERVAL_MINUTES", "85"))

# ── RSS Feeds ──────────────────────────────────────────────────────────────
RSS_FEEDS = [
    # ── English — Markets ──────────────────────────────────────────────────
    {
        "name": "WSJ Markets",
        "url":  "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",
        "lang": "en",
    },
    {
        "name": "MarketWatch",
        "url":  "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "lang": "en",
    },
    {
        "name": "CNBC Top News",
        "url":  "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        "lang": "en",
    },
    {
        "name": "CNBC World",
        "url":  "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
        "lang": "en",
    },
    {
        "name": "Bloomberg Markets",
        "url":  "https://feeds.bloomberg.com/markets/news.rss",
        "lang": "en",
    },
    {
        "name": "Seeking Alpha Market News",
        "url":  "https://seekingalpha.com/market_currents.xml",
        "lang": "en",
    },
    # ── English — Startups & M&A ───────────────────────────────────────────
    {
        "name": "TechCrunch",
        "url":  "https://techcrunch.com/feed/",
        "lang": "en",
    },
    # Twitter / X is fetched separately via feeds_twitter.py (API v2, not RSS) —
    # see _fetch_twitter_articles() in feeds.py.
    # ── Hebrew ─────────────────────────────────────────────────────────────
    {
        "name": "גלובס כללי",
        "url":  "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=1725",
        "lang": "he",
    },
    {
        "name": "גלובס שוק ההון",
        "url":  "https://www.globes.co.il/WebService/Rss/RssFeeder.asmx/FeederKeyword?iID=1383",
        "lang": "he",
    },
    {
        "name": "TheMarker שווקים",
        "url":  "https://www.themarker.com/srv/tm-markets",
        "lang": "he",
    },
    {
        "name": "גיקטיים",
        "url":  "https://www.geektime.co.il/feed/",
        "lang": "he",
    },
]

# ── World-news RSS feeds — used ONLY by the email digest pool ──────────────
# (`main.py --collect-email-pool`), never by the WhatsApp path. Kept separate
# from RSS_FEEDS above so a broken/blocked feed here can never affect what
# gets sent to WhatsApp. Each feed fails independently (see feeds.py) so a
# dead one just logs an error and is skipped — safe to list generously.
WORLD_RSS_FEEDS = [
    {
        "name": "NPR World",
        "url":  "https://feeds.npr.org/1004/rss.xml",
        "lang": "en",
    },
    {
        "name": "BBC World",
        "url":  "http://feeds.bbci.co.uk/news/world/rss.xml",
        "lang": "en",
    },
    {
        "name": "Al Jazeera",
        "url":  "https://www.aljazeera.com/xml/rss/all.xml",
        "lang": "en",
    },
    {
        "name": "Times of Israel",
        "url":  "https://www.timesofisrael.com/feed/",
        "lang": "en",
    },
    {
        "name": "Kyiv Independent",
        "url":  "https://kyivindependent.com/feed/",
        "lang": "en",
    },
    {
        "name": "Ynet חדשות",
        "url":  "https://www.ynet.co.il/Integration/StoryRss2.xml",
        "lang": "he",
    },
]

# ── Tech-news RSS feeds — used ONLY by the email digest pool's tech section ─
# (`main.py --collect-email-pool`, via email_tech_classifier.py), never by
# the WhatsApp path. Same isolation pattern as WORLD_RSS_FEEDS: each feed
# fails independently, safe to list generously.
TECH_RSS_FEEDS = [
    {
        "name": "TechCrunch",
        "url":  "https://techcrunch.com/feed/",
        "lang": "en",
    },
    {
        "name": "The Verge",
        "url":  "https://www.theverge.com/rss/index.xml",
        "lang": "en",
    },
    {
        "name": "Ars Technica",
        "url":  "https://feeds.arstechnica.com/arstechnica/index",
        "lang": "en",
    },
    {
        "name": "Wired",
        "url":  "https://www.wired.com/feed/rss",
        "lang": "en",
    },
    {
        "name": "גיקטיים",
        "url":  "https://www.geektime.co.il/feed/",
        "lang": "he",
    },
]

# ── "House stocks" watchlist — used ONLY by the morning brief's dedicated
# section (send_morning_brief.py / watchlist_news.py). For each entry, recent
# news is pulled (Yahoo Finance, no API key) and Claude decides what's
# actually significant enough to mention — most days most tickers get no
# mention at all. Fill in your own tickers; empty list = section is skipped.
WATCHLIST_STOCKS: list[dict] = [
    {"symbol": "HOOD",  "name": "Robinhood"},
    {"symbol": "IBKR",  "name": "Interactive Brokers"},
    {"symbol": "NBIS",  "name": "Nebius Group"},
    {"symbol": "DGXX",  "name": "Digi Power X"},
    {"symbol": "SHOP",  "name": "Shopify"},
    {"symbol": "SOFI",  "name": "SoFi"},
    {"symbol": "HIMS",  "name": "Hims & Hers"},
    {"symbol": "RKLB",  "name": "Rocket Lab"},
    {"symbol": "SPCX",  "name": "SpaceX"},
    {"symbol": "SMCI",  "name": "Super Micro Computer"},
    {"symbol": "DELL",  "name": "Dell Technologies"},
    {"symbol": "SPOT",  "name": "Spotify"},
    {"symbol": "META",  "name": "Meta"},
    {"symbol": "RDDT",  "name": "Reddit"},
    {"symbol": "AMZN",  "name": "Amazon"},
    {"symbol": "FTAI",  "name": "FTAI Aviation"},
    {"symbol": "PKE",   "name": "Park Aerospace"},
]


def validate_claude():
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env.")


def validate_whatsapp_credentials(provider: str):
    """Provider API credentials only — no destination check. Use this (not
    validate_provider) for callers with their own target, like
    send_morning_brief.py's MORNING_BRIEF_TO."""
    if provider == "twilio":
        missing = [k for k in ("TWILIO_SID", "TWILIO_AUTH_TOKEN") if not os.getenv(k)]
        if missing:
            raise EnvironmentError(f"Missing Twilio env vars: {', '.join(missing)}")
    elif provider == "green":
        missing = [k for k in ("GREEN_API_INSTANCE", "GREEN_API_TOKEN") if not os.getenv(k)]
        if missing:
            raise EnvironmentError(f"Missing Green API env vars: {', '.join(missing)}")


def validate_provider(provider: str):
    validate_whatsapp_credentials(provider)
    if not WHATSAPP_TO:
        raise EnvironmentError("WHATSAPP_TO is not set.")
