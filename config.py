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

# Source → email category, for splitting sent_log.json's WhatsApp-approved
# articles into "business" vs "tech" without any extra classification call.
# Anything not listed here (e.g. Twitter) falls back to "business".
EMAIL_SOURCE_CATEGORY: dict[str, str] = {
    "TechCrunch":    "tech",
    "גיקטיים":        "tech",
}
# Minimum minutes between consecutive *scheduled* runs (see the
# min-gap guard in main.py's run()). Manual workflow_dispatch / local runs
# never check or affect this.
MIN_SEND_INTERVAL_MINUTES = int(os.getenv("MIN_SEND_INTERVAL_MINUTES", "85"))

# ── Responder (רב מסר) — newsletter send, separate from email digest pool ──
# Used only by send_newsletter.py / responder_client.py / newsletter_composer.py.
#
# Two *different* Responder APIs are involved, with separate credentials:
#   - "V1" (legacy) — the only one with message create/test/send endpoints
#     (responder_client.py). Auth is a signed header, not a token. The
#     self-service "חיבורים חיצוניים (API)" account screen does NOT issue
#     these — they only come from Responder support (03-7177777).
#   - "V2.0" (current, self-service) — issued from that account screen
#     (Client ID / Client Secret / User Token), OAuth2 client_credentials.
#     Confirmed against Responder's official Swagger spec: it only covers
#     lists/subscribers/tags/webhooks — it has NO message-sending endpoint.
#     Used here (responder_v2_client.py) only to verify credentials and look
#     up RESPONDER_LIST_ID without waiting on the support call.
RESPONDER_C_KEY    = os.getenv("RESPONDER_C_KEY", "")
RESPONDER_C_SECRET = os.getenv("RESPONDER_C_SECRET", "")
RESPONDER_U_KEY    = os.getenv("RESPONDER_U_KEY", "")
RESPONDER_U_SECRET = os.getenv("RESPONDER_U_SECRET", "")
RESPONDER_LIST_ID  = os.getenv("RESPONDER_LIST_ID", "")

# V2.0 — from Settings → "חיבורים חיצוניים (API)" → "מפתח כללי לחשבון".
RESPONDER_V2_BASE_URL      = os.getenv("RESPONDER_V2_BASE_URL", "https://graph.responder.live/v2")
RESPONDER_V2_CLIENT_ID     = os.getenv("RESPONDER_V2_CLIENT_ID", "")
RESPONDER_V2_CLIENT_SECRET = os.getenv("RESPONDER_V2_CLIENT_SECRET", "")
RESPONDER_V2_USER_TOKEN    = os.getenv("RESPONDER_V2_USER_TOKEN", "")

NEWSLETTER_TEST_EMAIL = os.getenv("NEWSLETTER_TEST_EMAIL", "lioz2468@gmail.com")
NEWSLETTER_TEST_NAME  = os.getenv("NEWSLETTER_TEST_NAME", "ליוז")
# Second, independent opt-in on top of send_newsletter.py's --send-live flag.
# A real send goes to the whole subscriber list with no undo — Israeli
# anti-spam law (תיקון 40) makes an accidental unattended blast a real
# problem, not just an annoyance, so both gates must be set explicitly.
NEWSLETTER_ALLOW_LIVE_SEND = os.getenv("NEWSLETTER_ALLOW_LIVE_SEND", "false").lower() == "true"

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


def validate_claude():
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env.")


def validate_responder():
    missing = [k for k in (
        "RESPONDER_C_KEY", "RESPONDER_C_SECRET", "RESPONDER_U_KEY", "RESPONDER_U_SECRET",
    ) if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Missing Responder (V1 — message-sending) env vars: {', '.join(missing)}. "
            "These are NOT in the self-service API screen — call Responder support "
            "(03-7177777) and ask for API V1 credentials (c_key/c_secret/u_key/u_secret) "
            "for the Messages endpoint documented at github.com/responder/restapi."
        )


def validate_responder_v2():
    missing = [k for k in (
        "RESPONDER_V2_CLIENT_ID", "RESPONDER_V2_CLIENT_SECRET", "RESPONDER_V2_USER_TOKEN",
    ) if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Missing Responder V2 env vars: {', '.join(missing)}. "
            "Get them from Settings → 'חיבורים חיצוניים (API)' → 'מפתח כללי לחשבון' "
            "in the Responder account."
        )


def validate_provider(provider: str):
    if provider == "twilio":
        missing = [k for k in ("TWILIO_SID", "TWILIO_AUTH_TOKEN") if not os.getenv(k)]
        if missing:
            raise EnvironmentError(f"Missing Twilio env vars: {', '.join(missing)}")
    elif provider == "green":
        missing = [k for k in ("GREEN_API_INSTANCE", "GREEN_API_TOKEN") if not os.getenv(k)]
        if missing:
            raise EnvironmentError(f"Missing Green API env vars: {', '.join(missing)}")
    if not WHATSAPP_TO:
        raise EnvironmentError("WHATSAPP_TO is not set.")
