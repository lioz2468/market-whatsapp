"""Merges chunk analyses into a unified style profile + validation UI."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import anthropic

import config


# ── Public entry points ────────────────────────────────────────────────────

def build_draft_profile(analyses: list[dict]) -> dict:
    """Merge all chunk-level analyses into a single style profile dict."""
    if not analyses:
        raise ValueError("No analyses to merge.")

    vocab    = _merge_vocabulary(analyses)
    struct   = _merge_structure(analyses)
    tone     = _merge_tone(analyses)
    patterns = _merge_patterns(analyses)
    examples = _collect_examples(analyses)

    profile = {
        "vocabulary":        vocab,
        "sentence_structure": struct,
        "tone":              tone,
        "patterns":          patterns,
        "raw_examples": {
            "best_50_examples": examples[: config.MAX_EXAMPLES]
        },
        "_meta": {
            "source_chunks": len(analyses),
            "model_used": config.CLAUDE_MODEL,
        },
    }

    config.DRAFT_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  [profile] Draft saved → {config.DRAFT_PATH}")
    return profile


def validate_and_save(profile: dict) -> bool:
    """
    Display Hebrew summary, ask for confirmation, save if confirmed.
    Returns True if user confirmed and profile was saved.
    """
    _print_summary(profile)

    answer = input("\n  האם לשמור את הפרופיל? (y/n): ").strip().lower()
    if answer in {"y", "yes", "כן", "י"}:
        config.PROFILE_PATH.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n  ✓ הפרופיל נשמר → {config.PROFILE_PATH}")
        return True
    else:
        print("\n  ✗ הפרופיל לא נשמר. הרץ שוב `analyze` כדי ליצור טיוטה חדשה.")
        return False


def load_profile() -> dict:
    """Load the saved style profile (raises if not found)."""
    if not config.PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Profile not found at {config.PROFILE_PATH}. "
            "Run `python main.py all` first."
        )
    return json.loads(config.PROFILE_PATH.read_text(encoding="utf-8"))


def generate_test_text(topic: str, profile: dict) -> str:
    """Use Claude to write a short text about `topic` in the user's style."""
    config.validate()

    system = _build_style_system_prompt(profile)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    full_response = ""
    with client.messages.stream(
        model=config.CLAUDE_MODEL,
        max_tokens=600,
        system=system,
        messages=[
            {
                "role": "user",
                "content": f"כתוב פסקה אחת קצרה (3-5 משפטים) בסגנון שלי על הנושא: {topic}. גרסה אחת בלבד.",
            }
        ],
    ) as stream:
        for text in stream.text_stream:
            full_response += text
            print(text, end="", flush=True)

    print()  # newline after streaming
    return full_response


# ── Merging helpers ────────────────────────────────────────────────────────

def _merge_vocabulary(analyses: list[dict]) -> dict:
    all_words: list[str] = []
    slang: list[str] = []
    english: list[str] = []
    transitions: list[str] = []
    fillers: list[str] = []

    for a in analyses:
        v = a.get("vocabulary", {})
        all_words.extend(v.get("frequent_words", []))
        slang.extend(v.get("slang", []))
        english.extend(v.get("english_words_in_hebrew", []))
        transitions.extend(v.get("transition_words", []))
        fillers.extend(v.get("filler_words", []))

    return {
        "frequent_words":           _top_by_freq(all_words, 30),
        "slang":                    _dedupe(slang),
        "english_words_in_hebrew":  _dedupe(english),
        "transition_words":         _dedupe(transitions),
        "filler_words":             _dedupe(fillers),
    }


def _merge_structure(analyses: list[dict]) -> dict:
    lengths = []
    styles  = []
    punct_keys = ["parentheses", "dashes", "ellipsis", "exclamation", "questions_rhetorical"]
    punct_counts: dict[str, int] = {k: 0 for k in punct_keys}
    context_count = 0

    for a in analyses:
        s = a.get("sentence_structure", {})
        if s.get("avg_length"):
            lengths.append(s["avg_length"])
        if s.get("style"):
            styles.append(s["style"])
        for k in punct_keys:
            if s.get("punctuation_habits", {}).get(k):
                punct_counts[k] += 1
        if s.get("starts_with_context"):
            context_count += 1

    total = len(analyses)
    return {
        "avg_length": _majority(lengths) or "medium",
        "style":      _majority(styles) or "mixed",
        "punctuation_habits": {
            k: (punct_counts[k] > total // 2) for k in punct_keys
        },
        "starts_with_context": context_count > total // 2,
    }


def _merge_tone(analyses: list[dict]) -> dict:
    fields = [
        "default", "when_excited", "when_skeptical",
        "when_urgent", "when_disappointed", "formality", "confidence_level",
    ]
    humor_levels = []
    merged: dict[str, Any] = {}

    for a in analyses:
        t = a.get("tone", {})
        for f in fields:
            val = t.get(f)
            if val and f not in merged:
                merged[f] = val
        if t.get("humor_level"):
            humor_levels.append(t["humor_level"])

    merged["humor_level"] = _majority(humor_levels) or "medium"
    return merged


def _merge_patterns(analyses: list[dict]) -> dict:
    openings:   list[str] = []
    closings:   list[str] = []
    signatures: list[str] = []
    meta_fields = ["metaphor_style", "explanation_style", "numbering_style"]
    meta: dict[str, str] = {}

    for a in analyses:
        p = a.get("patterns", {})
        openings.extend(p.get("opening_styles", []))
        closings.extend(p.get("closing_styles", []))
        signatures.extend(p.get("signature_phrases", []))
        for f in meta_fields:
            if p.get(f) and f not in meta:
                meta[f] = p[f]

    result: dict[str, Any] = {
        "opening_styles":  _dedupe(openings)[:10],
        "closing_styles":  _dedupe(closings)[:5],
        "signature_phrases": _dedupe(signatures)[:20],
    }
    result.update(meta)
    return result


def _collect_examples(analyses: list[dict]) -> list[str]:
    examples = []
    for a in analyses:
        examples.extend(a.get("examples", []))
    return _dedupe(examples)


# ── Display / Summary ──────────────────────────────────────────────────────

def _print_summary(profile: dict) -> None:
    BOLD  = "\033[1m"
    CYAN  = "\033[36m"
    GREEN = "\033[32m"
    RESET = "\033[0m"

    print(f"\n{'='*60}")
    print(f"{BOLD}{CYAN}  📊 סיכום פרופיל הסגנון{RESET}")
    print(f"{'='*60}")

    v = profile.get("vocabulary", {})
    s = profile.get("sentence_structure", {})
    t = profile.get("tone", {})
    p = profile.get("patterns", {})

    print(f"\n{BOLD}🔤 אוצר מילים:{RESET}")
    print(f"  מילים שחוזרות:   {', '.join(v.get('frequent_words', [])[:10])}")
    print(f"  סלנג ייחודי:     {', '.join(v.get('slang', [])[:8])}")
    print(f"  אנגלית בעברית:   {', '.join(v.get('english_words_in_hebrew', [])[:8])}")
    print(f"  מילות מעבר:      {', '.join(v.get('transition_words', [])[:6])}")
    print(f"  מילות מילוי:     {', '.join(v.get('filler_words', [])[:6])}")

    print(f"\n{BOLD}📝 מבנה משפטים:{RESET}")
    print(f"  אורך ממוצע:   {s.get('avg_length', '—')}")
    print(f"  סגנון:        {s.get('style', '—')}")
    ph = s.get("punctuation_habits", {})
    active_punct = [k for k, v in ph.items() if v]
    print(f"  פיסוק:        {', '.join(active_punct) or '—'}")

    print(f"\n{BOLD}🎭 טון ואישיות:{RESET}")
    print(f"  ברירת מחדל:  {t.get('default', '—')}")
    print(f"  פורמליות:    {t.get('formality', '—')}")
    print(f"  הומור:        {t.get('humor_level', '—')}")
    print(f"  ביטחון עצמי: {t.get('confidence_level', '—')}")
    print(f"  כשנלהב:      {t.get('when_excited', '—')}")
    print(f"  כשספקן:      {t.get('when_skeptical', '—')}")

    print(f"\n{BOLD}✨ 5 ביטויים ייחודיים שזוהו:{RESET}")
    sigs = p.get("signature_phrases", [])[:5]
    for i, phrase in enumerate(sigs, 1):
        print(f"  {i}. \"{phrase}\"")

    print(f"\n{BOLD}📌 3 כללי אצבע:{RESET}")
    rules = _derive_rules(profile)
    for i, rule in enumerate(rules[:3], 1):
        print(f"  {i}. {rule}")

    examples = profile.get("raw_examples", {}).get("best_50_examples", [])
    if examples:
        print(f"\n{BOLD}💬 דוגמאות אופייניות:{RESET}")
        for ex in examples[:4]:
            print(f"  • \"{ex}\"")

    meta = profile.get("_meta", {})
    print(f"\n  [{meta.get('source_chunks', '?')} chunks נותחו | מודל: {meta.get('model_used', '—')}]")
    print(f"{'='*60}")


def _derive_rules(profile: dict) -> list[str]:
    """Generate human-readable rules of thumb from the profile."""
    rules = []
    t = profile.get("tone", {})
    v = profile.get("vocabulary", {})
    s = profile.get("sentence_structure", {})
    p = profile.get("patterns", {})

    if t.get("when_excited"):
        ex_words = v.get("slang", [])
        hint = f" (כגון: {', '.join(ex_words[:2])})" if ex_words else ""
        rules.append(f"כשמתרגש — {t['when_excited']}{hint}")

    if v.get("english_words_in_hebrew"):
        rules.append(
            f"משלב אנגלית בצורה טבעית: {', '.join(v['english_words_in_hebrew'][:4])}"
        )

    if s.get("style") == "short_choppy":
        rules.append("משפטים קצרים וחתוכים — לא מבזבז מילים")
    elif s.get("style") == "flowing":
        rules.append("זורם ומסביר — בונה הקשר לפני המסקנה")
    elif s.get("style") == "mixed":
        rules.append("מחליף בין משפטים קצרים לארוכים לפי עצימות הרגש")

    if v.get("transition_words"):
        rules.append(
            f"משתמש במילות מעבר: {', '.join(v['transition_words'][:4])}"
        )

    if t.get("formality") in {"informal", "street"}:
        rules.append("טון לא פורמלי לחלוטין — מדבר לחבר, לא לקהל")

    if p.get("signature_phrases"):
        rules.append(
            f"ביטוי חתימה: \"{p['signature_phrases'][0]}\""
        )

    if not rules:
        rules = [
            "סגנון עקבי ומזוהה לאורך כל התכנים",
            "שילוב של אוטוריטה עם שפה נגישה",
            "ישיר לעניין — לא מחכה למסקנה",
        ]

    return rules


# ── Style system prompt (for test command) ─────────────────────────────────

def _build_style_system_prompt(profile: dict) -> str:
    v = profile.get("vocabulary", {})
    s = profile.get("sentence_structure", {})
    t = profile.get("tone", {})
    p = profile.get("patterns", {})

    sig_phrases = ", ".join(f'"{ph}"' for ph in p.get("signature_phrases", [])[:6])
    slang       = ", ".join(v.get("slang", [])[:6])
    eng_words   = ", ".join(v.get("english_words_in_hebrew", [])[:6])
    transitions = ", ".join(v.get("transition_words", [])[:5])
    fillers     = ", ".join(v.get("filler_words", [])[:4])
    examples    = profile.get("raw_examples", {}).get("best_50_examples", [])[:3]

    examples_str = "\n".join(f'  • "{e}"' for e in examples)

    return f"""אתה כותב בדיוק בסגנון של אדם ספציפי — כתב כלכלי שמסביר אירועים, לא מוכר אותם.

**פרופיל סגנון:**
טון: {t.get("default", "—")} | פורמליות: {t.get("formality", "—")} | הומור: {t.get("humor_level", "—")}
מבנה: {s.get("style", "—")} | אורך משפט: {s.get("avg_length", "—")}
ביטויי חתימה: {sig_phrases or "—"}
סלנג: {slang or "—"}
אנגלית בעברית: {eng_words or "—"}
מילות מעבר: {transitions or "—"}

**דוגמאות לסגנון:**
{examples_str or "  —"}

**מה לעשות:**
- הסבר מה קרה → למה זה משמעותי → מה ההשפעה
- יומיומי וישיר — כמו שמסביר לחבר חכם, לא לקהל שצריך לשכנע
- מותר להביע התרגשות אם המספרים באמת מרשימים — אבל בצורה עניינית ("זה מספר גדול" ולא "הזדמנות פז")
- תן זווית ראיה שמעמיקה את הדיווח הרגיל, לא מחליפה אותו

**מה אסור בתכלית האיסור:**
- אין FOMO — לא "מי שלא בפנים מפספס", לא "כסף על הרצפה", לא "הרגע הכי חם"
- "מטורף" / "זה מטורף" — אסור
- "מבסוט" — אסור
- "הזדמנות פז" — אסור
- אין המלצות קנייה/מכירה — אתה מדווח, לא מייעץ
- אין כותרות סנסציוניות — תוכן עובדתי בלבד
- אל תסיים ב"אוקיי?", "אוקי?", "נכון?" — אל תסיים בשאלה רטורית
- אל תסביר שאתה כותב בסגנון מישהו — פשוט כתוב
- כתוב גרסה אחת בלבד — ללא חלופות, ללא "גרסה א' / גרסה ב'"  """


# ── Utility functions ──────────────────────────────────────────────────────

def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        norm = item.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(item.strip())
    return result


def _top_by_freq(items: list[str], n: int) -> list[str]:
    counter = Counter(w.strip().lower() for w in items if w.strip())
    return [word for word, _ in counter.most_common(n)]


def _majority(items: list[str]) -> str | None:
    if not items:
        return None
    return Counter(items).most_common(1)[0][0]
