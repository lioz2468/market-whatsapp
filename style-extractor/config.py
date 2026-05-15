"""Central configuration — loaded once at startup."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
RAW_CONTENT_DIR = BASE_DIR / "raw_content"
PROCESSED_DIR   = BASE_DIR / "processed"
PROFILE_PATH    = BASE_DIR / "style_profile.json"
DRAFT_PATH      = PROCESSED_DIR / "style_profile_draft.json"

# Sub-directories (auto-created on first use)
PODCASTS_RAW_DIR   = RAW_CONTENT_DIR / "podcasts"
POSTS_RAW_DIR      = RAW_CONTENT_DIR / "posts"
TRANSCRIPTS_DIR    = PROCESSED_DIR / "transcripts"
POSTS_PROC_DIR     = PROCESSED_DIR / "posts"
ANALYSIS_DIR       = PROCESSED_DIR / "analysis"

# ── API Keys ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
HUGGINGFACE_TOKEN  = os.getenv("HUGGINGFACE_TOKEN", "")

# ── Model Settings ─────────────────────────────────────────────────────────
WHISPER_MODEL    = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "he")
CLAUDE_MODEL     = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# ── Analysis Settings ──────────────────────────────────────────────────────
MAX_CHUNK_WORDS     = int(os.getenv("MAX_CHUNK_WORDS", "2000"))
MAX_EXAMPLES        = 50
MIN_WORD_FREQ       = 3     # min occurrences to include in frequent_words

# Supported audio extensions
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".aac"}

# Supported text extensions
TEXT_EXTENSIONS  = {".txt", ".md"}


def ensure_dirs():
    """Create all processed sub-directories."""
    for d in [PROCESSED_DIR, TRANSCRIPTS_DIR, POSTS_PROC_DIR, ANALYSIS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def validate():
    """Raise if required env vars are missing."""
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
