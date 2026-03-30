"""Rewrite composed messages in the user's personal style (optional step)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import anthropic

import config
from classifier import ClassificationResult


# ── Profile loader ─────────────────────────────────────────────────────────

def load_profile(path: Optional[Path] = None) -> Optional[dict]:
    """Load style_profile.json. Returns None if file doesn't exist."""
    profile_path = path or config.STYLE_PROFILE_PATH
    if not profile_path.exists():
        return None
    try:
        return json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  [humanizer] ⚠ Could not load style profile: {exc}")
        return None


_BANNED_WORDS = ["מטורף", "כסף על הרצפה", "הזדמנות פז", "חבר'ה", "מבסוט", "אוקיי?", "אוקי?", "נכון?"]


def _filter_examples(examples: list[str]) -> list[str]:
    """Remove examples that contain banned words."""
    return [e for e in examples if not any(b in e for b in _BANNED_WORDS)]


def build_system_prompt(profile: dict) -> str:
    """Build a Claude system prompt from the style profile."""
    v = profile.get("vocabulary", {})
    s = profile.get("sentence_structure", {})
    t = profile.get("tone", {})
    p = profile.get("patterns", {})

    # Filter signature phrases and slang to exclude banned terms
    sig_raw   = [ph for ph in p.get("signature_phrases", []) if not any(b in ph for b in _BANNED_WORDS)]
    slang_raw = [w for w in v.get("slang", []) if w not in _BANNED_WORDS and not any(b in w for b in _BANNED_WORDS)]

    sig   = ", ".join(f'"{ph}"' for ph in sig_raw[:5])
    slang = ", ".join(slang_raw[:6])
    eng   = ", ".join(v.get("english_words_in_hebrew", [])[:6])
    trans = ", ".join(v.get("transition_words", [])[:5])

    all_examples = profile.get("raw_examples", {}).get("best_50_examples", [])
    clean_examples = _filter_examples(all_examples)[:3]
    ex_str = "\n".join(f'  • "{e}"' for e in clean_examples)

    return f"""אתה מעצב מחדש הודעות WhatsApp בסגנון ייחודי של אדם ספציפי.

⛔ אסור בתכלית האיסור — גם אם המילים האלה מופיעות בפרופיל או בדוגמאות:
- "מטורף" / "זה מטורף" / "מטורף שכזה" — אסור לחלוטין
- "מבסוט" — אסור לחלוטין
- "כסף על הרצפה" — אסור לחלוטין
- "הזדמנות פז" — אסור לחלוטין
- FOMO מכל סוג ("מי שלא בפנים מפספס", "הזדמנות שלא חוזרת") — אסור
- המלצות קנייה/מכירה — אסור
- פתיחה ב"חבר'ה" — אסור
- "אוקיי?", "אוקי?", "נכון?" — אסור לחלוטין, גם באמצע וגם בסוף הודעה

פרופיל הסגנון:
• טון: {t.get("default", "—")} | פורמליות: {t.get("formality", "—")} | הומור: {t.get("humor_level", "—")}
• מבנה: {s.get("style", "—")} | אורך: {s.get("avg_length", "—")}
• ביטויי חתימה: {sig or "—"}
• סלנג: {slang or "—"}
• אנגלית בעברית: {eng or "—"}
• מילות מעבר: {trans or "—"}

דוגמאות לסגנון (ללא מילות הבאן):
{ex_str or "  —"}

כללים:
- שמור על אותו מידע — אל תוסיף ואל תוריד עובדות
- שנה רק את הסגנון, הטון, ומבנה המשפטים
- שמור על ההודעה קצרה (40-80 מילים) — אל תחתוך משפטים באמצע, סיים אותם
- השתמש בביטויים מהפרופיל במשורה — מקסימום 1-2 ביטויי סלנג להודעה, לא בכל משפט
- "אשכרה" — מקסימום פעם אחת בכל 3-4 הודעות. ברוב ההודעות: לא בכלל
- אם ההודעה כבר נשמעת טבעי, אל תוסיף סלנג בכוח
- החזר רק את ההודעה הסופית, ללא הסברים"""


# ── Public entry points ────────────────────────────────────────────────────

async def humanize_all(
    results: list[ClassificationResult],
    profile: Optional[dict] = None,
) -> list[ClassificationResult]:
    """
    Add `.humanized_msg` to each result.
    If profile is None, loads from config.STYLE_PROFILE_PATH.
    Skips silently if no profile found.
    """
    if profile is None:
        profile = load_profile()

    if profile is None:
        return results  # no profile → skip humanizer

    print(f"  [humanizer] Applying style profile to {len(results)} message(s)…")

    system    = build_system_prompt(profile)
    client    = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CLAUDE)

    tasks = [_humanize_one(client, semaphore, system, r) for r in results]
    await asyncio.gather(*tasks)
    return results


# ── Single message humanizer ───────────────────────────────────────────────

async def _humanize_one(
    client:    anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    system:    str,
    result:    ClassificationResult,
    attempt:   int = 1,
) -> None:
    if not result.message:
        return

    async with semaphore:
        try:
            response = await client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=400,
                system=system,
                messages=[{
                    "role": "user",
                    "content": f"שכתב בסגנון שלי:\n\n{result.message}",
                }],
            )
            result.humanized_msg = response.content[0].text.strip()

        except anthropic.RateLimitError:
            if attempt <= 3:
                await asyncio.sleep((2 ** (attempt - 1)) * 5)
                await _humanize_one(client, semaphore, system, result, attempt + 1)
        except Exception as exc:
            print(f"  [humanizer] ⚠ Skipping humanization: {exc}")
            # Keep original message
