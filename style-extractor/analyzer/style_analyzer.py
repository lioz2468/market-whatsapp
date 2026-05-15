"""Style analysis using Claude API — processes content in chunks."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import anthropic

import config

# ── System prompt ──────────────────────────────────────────────────────────

_SYSTEM = """אתה מומחה לניתוח סגנון כתיבה ודיבור בעברית.
תנתח טקסטים ותחזיר JSON מובנה ומדויק בלבד — ללא הסברים, ללא markdown, ללא ```json.
התמקד בדפוסים ייחודיים, ביטויים חוזרים, ומאפייני סגנון אמיתיים מהטקסט.
רשום רק דברים שאכן מופיעים בטקסט — אל תמציא."""

# ── Chunk-level analysis prompt ────────────────────────────────────────────

_CHUNK_PROMPT = """נתח את סגנון הכתיבה/דיבור בטקסט הבא.

===CONTENT START===
{content}
===CONTENT END===

החזר JSON בדיוק עם המבנה הזה (ערכים לפי מה שמופיע בפועל בטקסט):
{{
  "vocabulary": {{
    "frequent_words": ["מילה1", "מילה2"],
    "slang": ["סלנג1", "סלנג2"],
    "english_words_in_hebrew": ["word1", "word2"],
    "transition_words": ["אז", "בעצם", "תראה"],
    "filler_words": ["כאילו", "אה", "נו"]
  }},
  "sentence_structure": {{
    "avg_length": "short|medium|long",
    "style": "short_choppy|flowing|mixed",
    "punctuation_habits": {{
      "parentheses": false,
      "dashes": false,
      "ellipsis": false,
      "exclamation": false,
      "questions_rhetorical": false
    }},
    "starts_with_context": false
  }},
  "tone": {{
    "default": "תיאור הטון הכללי",
    "when_excited": "איך נשמע ההתרגשות",
    "when_skeptical": "איך נשמע הספקנות",
    "when_urgent": "איך נשמעת הדחיפות",
    "when_disappointed": "איך נשמעת האכזבה",
    "humor_level": "none|low|medium|high",
    "formality": "formal|semi-formal|informal|street",
    "confidence_level": "low|medium|high|very_high"
  }},
  "patterns": {{
    "opening_styles": ["דרך פתיחה1", "דרך פתיחה2"],
    "closing_styles": ["דרך סיום1"],
    "signature_phrases": ["ביטוי1", "ביטוי2", "ביטוי3"],
    "metaphor_style": "תיאור המטאפורות האופייניות",
    "explanation_style": "איך מסביר מושגים",
    "numbering_style": "האם משתמש במספרים/סטטיסטיקות"
  }},
  "examples": [
    "משפט לדוגמה אופייני 1",
    "משפט לדוגמה אופייני 2",
    "משפט לדוגמה אופייני 3"
  ]
}}"""


# ── Public entry point ─────────────────────────────────────────────────────

def analyze_all_content() -> list[dict]:
    """
    Read all processed content, chunk it, analyze each chunk with Claude.
    Returns list of raw analysis dicts (one per chunk).
    Caches chunk analyses to disk.
    """
    config.ensure_dirs()
    config.validate()

    all_items = _load_all_processed()
    if not all_items:
        raise ValueError(
            "No processed content found. Run `python main.py ingest` first."
        )

    chunks = _build_chunks(all_items)
    print(f"\n  [analyze] {len(all_items)} source(s) → {len(chunks)} chunk(s) to analyze")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    results = []

    for i, chunk in enumerate(chunks, 1):
        cache_path = config.ANALYSIS_DIR / f"chunk_{i:03d}.json"
        if cache_path.exists():
            print(f"  [analyze] Chunk {i}/{len(chunks)} — using cache")
            with open(cache_path, "r", encoding="utf-8") as fh:
                results.append(json.load(fh))
            continue

        print(f"  [analyze] Chunk {i}/{len(chunks)} (~{len(chunk.split())} words)…")
        analysis = _analyze_chunk(client, chunk, attempt=1)

        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(analysis, fh, ensure_ascii=False, indent=2)
        results.append(analysis)

        # Polite rate-limiting between chunks
        if i < len(chunks):
            time.sleep(1)

    return results


# ── Loading processed content ──────────────────────────────────────────────

def _load_all_processed() -> list[dict]:
    items = []

    # Transcripts (podcasts)
    for f in sorted(config.TRANSCRIPTS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        text = data.get("text", "").strip()
        if text:
            items.append({"text": text, "source": f.name, "type": "podcast"})

    # Posts
    for f in sorted(config.POSTS_PROC_DIR.glob("*.txt")):
        text = f.read_text(encoding="utf-8").strip()
        if text:
            items.append({"text": text, "source": f.name, "type": "post"})

    return items


# ── Chunking ───────────────────────────────────────────────────────────────

def _build_chunks(items: list[dict]) -> list[str]:
    """Combine all content into word-count-limited chunks."""
    all_text = "\n\n".join(
        f"[{item['type'].upper()} — {item['source']}]\n{item['text']}"
        for item in items
    )
    words = all_text.split()
    chunks = []
    for i in range(0, len(words), config.MAX_CHUNK_WORDS):
        chunk = " ".join(words[i : i + config.MAX_CHUNK_WORDS])
        chunks.append(chunk)
    return chunks


# ── Claude call ────────────────────────────────────────────────────────────

def _analyze_chunk(client: anthropic.Anthropic, content: str, attempt: int) -> dict:
    """Send one chunk to Claude and return parsed analysis dict."""
    try:
        full_response = ""
        with client.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[
                {"role": "user", "content": _CHUNK_PROMPT.format(content=content)}
            ],
        ) as stream:
            for text in stream.text_stream:
                full_response += text

        return _parse_json(full_response)

    except anthropic.RateLimitError:
        if attempt <= 3:
            wait = 30 * attempt
            print(f"    Rate limited — waiting {wait}s…")
            time.sleep(wait)
            return _analyze_chunk(client, content, attempt + 1)
        raise
    except anthropic.APIError as exc:
        if attempt <= 2:
            print(f"    API error ({exc}) — retrying in 10s…")
            time.sleep(10)
            return _analyze_chunk(client, content, attempt + 1)
        raise


def _parse_json(raw: str) -> dict:
    """Extract and parse JSON from Claude's response."""
    # Strip any accidental markdown fences
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
    raw = raw.rstrip("`").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to find the JSON object inside the string
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        print(f"    [warn] Could not parse JSON from response:\n{raw[:300]}")
        return {}
