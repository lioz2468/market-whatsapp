"""Text ingestion: posts, WhatsApp exports, tweets."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import config


# ── Public entry point ─────────────────────────────────────────────────────

def ingest_posts() -> list[dict]:
    """
    Read all text files from raw_content/posts/.
    Returns list of post dicts (text + metadata).
    """
    config.ensure_dirs()

    post_files = sorted(
        f for f in config.POSTS_RAW_DIR.iterdir()
        if f.suffix.lower() in config.TEXT_EXTENSIONS | {".docx"}
    )

    if not post_files:
        print("  [text] No post files found in raw_content/posts/")
        return []

    results = []
    for post_file in post_files:
        cache_path = config.POSTS_PROC_DIR / f"{post_file.stem}.txt"

        if cache_path.exists():
            print(f"  [text] Using cached post → {cache_path.name}")
            text = cache_path.read_text(encoding="utf-8")
        else:
            print(f"  [text] Reading: {post_file.name}")
            text = _read_file(post_file)
            cache_path.write_text(text, encoding="utf-8")
            print(f"  [text] Saved → {cache_path.name}")

        if text.strip():
            results.append({"text": text, "source": post_file.name, "type": "post"})

    print(f"  [text] Loaded {len(results)} post(s).")
    return results


def ingest_whatsapp() -> list[dict]:
    """
    Read WhatsApp chat exports from raw_content/whatsapp/.
    Strips timestamps and contact names, keeps only message content.
    """
    config.ensure_dirs()
    wa_dir = config.RAW_CONTENT_DIR / "whatsapp"
    if not wa_dir.exists():
        return []

    results = []
    for wa_file in sorted(wa_dir.iterdir()):
        if wa_file.suffix.lower() not in {".txt", ".md"}:
            continue
        raw = wa_file.read_text(encoding="utf-8", errors="ignore")
        cleaned = _clean_whatsapp(raw)
        if cleaned.strip():
            results.append({"text": cleaned, "source": wa_file.name, "type": "whatsapp"})
            print(f"  [text] Loaded WhatsApp export: {wa_file.name}")

    return results


def ingest_tweets() -> list[dict]:
    """
    Read tweet files from raw_content/tweets/.
    Strips @mentions, hashtags kept (they reveal style).
    """
    config.ensure_dirs()
    tweets_dir = config.RAW_CONTENT_DIR / "tweets"
    if not tweets_dir.exists():
        return []

    results = []
    for tweet_file in sorted(tweets_dir.iterdir()):
        if tweet_file.suffix.lower() not in {".txt", ".md"}:
            continue
        text = tweet_file.read_text(encoding="utf-8", errors="ignore")
        if text.strip():
            results.append({"text": text, "source": tweet_file.name, "type": "tweet"})
            print(f"  [text] Loaded tweets: {tweet_file.name}")

    return results


# ── File readers ───────────────────────────────────────────────────────────

def _read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise ImportError("python-docx is required to read .docx files. Run: pip install python-docx")


# ── WhatsApp cleanup ───────────────────────────────────────────────────────

# Matches lines like:
#   [12/03/2024, 14:30:00] ContactName: message
#   12/03/2024, 14:30 - ContactName: message
_WA_LINE = re.compile(
    r"""
    (?:
        \[[\d/\.\-]+,\s*[\d:]+\]\s*   # [date, time]
        |
        [\d/\.\-]+,\s*[\d:]+\s*-\s*   # date, time -
    )
    [^:]+:\s*                          # ContactName:
    """,
    re.VERBOSE,
)

def _clean_whatsapp(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip system messages
        if any(k in line for k in ["הצטרף", "עזב", "הוסיפ", "שינה", "encrypted", "omitted"]):
            continue
        cleaned = _WA_LINE.sub("", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)
