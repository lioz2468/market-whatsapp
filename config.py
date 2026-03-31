"""Central configuration — loaded once at import time."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR           = Path(__file__).parent
SENT_LOG_PATH      = BASE_DIR / "sent_log.json"
# style_profile.json lives in the sibling style-extractor project
STYLE_PROFILE_PATH = BASE_DIR.parent / "style-extractor" / "style_profile.json"

# ── Claude ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL          = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-0")
MAX_CONCURRENT_CLAUDE = int(os.getenv("MAX_CONCURRENT_CLAUDE", "2"))

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

# ── Filter settings ────────────────────────────────────────────────────────
MIN_IMPORTANCE_SCORE = int(os.getenv("MIN_IMPORTANCE_SCORE", "7"))
MAX_ARTICLES_PER_RUN = int(os.getenv("MAX_ARTICLES_PER_RUN", "1"))
DIGEST_HOURS         = int(os.getenv("DIGEST_HOURS", "12"))

# ── RSS Feeds ──────────────────────────────────────────────────────────────
RSS_FEEDS = [
    # ── English ────────────────────────────────────────────────────────────
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
        "name": "Reuters Business & Finance",
        "url":  "https://www.reutersagency.com/feed/?best-topics=business-finance",
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
        "name": "כלכליסט כללי",
        "url":  "https://www.calcalist.co.il/GeneralRSS/0,16335,L-8,00.xml",
        "lang": "he",
    },
    {
        "name": "כלכליסט שוק ההון",
        "url":  "https://www.calcalist.co.il/GeneralRSS/0,16335,L-3913,00.xml",
        "lang": "he",
    },
]


def validate_claude():
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env.")


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
