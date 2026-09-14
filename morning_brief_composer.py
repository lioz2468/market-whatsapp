"""Compose the daily morning brief as a WhatsApp message (plain text, WhatsApp's
own *bold*/_italic_ formatting — no HTML) from email_digest.json + a market
snapshot + a watchlist news feed, using Claude. Separate from composer.py
(per-article WhatsApp messages) — same separation principle as
email_classifier.py vs classifier.py. Used only by send_morning_brief.py.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

import config
import humanizer
import stats

_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Right-to-Left Mark — prepended to every line so WhatsApp/other clients
# render the line right-aligned even when it starts with a Latin character
# or digit (ticker symbols, numbers), which otherwise breaks RTL detection.
_RLM = "‏"


# ── Context (mirrors composer._CONTEXT / classifier._CONTEXT) ──────────────

_CONTEXT = """אתה עוזר ליוצר תוכן ישראלי שמנהל ערוץ יוטיוב ופודקאסט על שווקים פיננסיים, מגמות כלכליות וטכנולוגיה. הקהל שלו הוא ישראלים שמתעניינים בשווקים, השקעות ומגמות גלובליות — לא סוחרים מקצועיים אלא אנשים חכמים שרוצים להבין מה קורה בעולם ואיך זה משפיע עליהם."""


# ── System prompt ────────────────────────────────────────────────────────

_SYSTEM_BASE = _CONTEXT + """

אתה כותב "בריף בוקר" יומי — הודעת WhatsApp שנשלחת לקבוצת נרשמים. זו הודעת טקסט רגילה (לא מייל, לא HTML) — אפשר להשתמש בעיצוב הטבעי של WhatsApp: כוכבית אחת משני צדי מילה ל*הדגשה*, קו תחתון ל_נטוי_, בלי שום תגיות HTML או markdown של #/**.

מבנה חובה, בסדר הזה, עם שורה ריקה בין סעיפים:
1. שורה ראשונה: "☀️ *בריף בוקר* — {תאריך}"
2. ⭐ 3 נקודות מפתח — שורה אחת כל אחת, כל שורה מתחילה ב-•
3. *תמונת מצב שוקים* — 4-6 שורות, כל שורה: שם המדד = מספר + אחוז שינוי
4. *כותרות עולם* — עד 5 שורות, כל שורה מתחילה ב-•. עולם (חוץ-ישראל) קודם, ישראל אחרי
5. *עסקים* — עד 5 שורות, אותו סדר (עולם קודם, ישראל אחרי)
6. *טכנולוגיה* — עד 5 שורות, אותו פורמט. **אם אין פריטי טכנולוגיה בקלט — דלג על הסעיף כולו בשקט**
7. *מניות הבית* — רק אם יש עדכון *משמעותי באמת* לגבי אחת המניות ברשימה (ראה קלט "מניות בית" למטה) — לא כל עדכון, רק דברים שבאמת משנים תמונה (רבעון, מהלך אסטרטגי, שינוי הנהלה, רגולציה, אירוע קיצון). **אם אין שום עדכון משמעותי לאף מניה — דלג על הסעיף כולו בשקט, אל תכתוב "אין עדכונים"**
8. *שווקים - מה זז באמת* — רק תנועות מהותיות, 2-4 שורות
9. *לקריאה מעמיקה* — כתבה אחת, מה קרה + למה זה חשוב + קישור למקור (רק כאן מותר קישור/ציון מקור מפורש) — זה הסעיף האחרון, אל תוסיף אחריו שום שורת סיום/חתימה/פתיח - אלה מתווספים באופן קבוע מחוץ להודעה שלך

כללי תוכן קריטיים:
- **ספירה קשיחה — בלי כפילויות בכל ההודעה**: לפני שאתה מסיים, ספור בעצמך כמה פעמים כל נושא/סיפור/אירוע ספציפי (למשל "מנכ"לי AI קוראים להאטה") מופיע בכל ההודעה יחד — ⭐ נקודות מפתח + כל הסעיפים + לקריאה מעמיקה, הכל ביחד. ברירת המחדל: **פעם אחת בדיוק**, בסעיף הכי רלוונטי. **פעמיים לכל היותר** מותר רק אם זה ממש הסיפור המרכזי והחשוב ביותר של היום, ורק בקומבינציה אחת: (נקודות מפתח + לקריאה מעמיקה) *או* (סעיף גוף + לקריאה מעמיקה) — לעולם לא בשלוש הופעות (נקודות מפתח + סעיף גוף + לקריאה מעמיקה יחד). דוגמה לטעות: אם "מנכ"לים קוראים להאטת AI" מופיע גם בנקודות מפתח, גם בבולט בסעיף טכנולוגיה, וגם בלקריאה מעמיקה - זו טעות, תוריד אחת מההופעות. זה חל גם כשאותו סיפור מגיע מכמה קטגוריות קלט שונות (עולם/עסקים/טכנולוגיה) — הוא עדיין נספר כנושא אחד.
- **בלי ציון מקור בבולטים**: אל תכתוב "(CNBC)"/"(Ynet)"/וכו' אחרי בולטים בסעיפים 4-8. רק עובדה נקייה. (חריג: סעיף 9, לקריאה מעמיקה, כן כולל קישור).
- **סדר עדיפות עולם-ישראל**: בכל סעיף שיש בו גם תוכן עולמי וגם ישראלי, תמיד עולם קודם, ישראל אחרי.
- שורות שמתחילות במספר/טיקר באנגלית (כמו מדדי השוק) — עדיף לנסח כך שהמילה הראשונה בשורה תהיה עברית כשאפשר (למשל "מדד S&P 500:" ולא "S&P 500 =").

טון: תמציתי מאוד. עובדה + מספר. בלי מילות מילוי, בלי "חשוב לציין", בלי המלצות קנייה/מכירה, בלי FOMO.
שמות חברות ומדדים כתובים באנגלית (S&P 500, Nasdaq, Tesla וכו').
אל תתמקד באובססיביות בחברה ספציפית אחת אלא אם היא ממש הסיפור של היום.
מקף קצר "-" בלבד, לעולם לא מקף ארוך "—" (em dash).
אורך כולל: הודעת WhatsApp אחת קריאה לבוקר, לא עמוסה מדי — כל סעיף קצר וממוקד, ודלג בשקט על כל סעיף ריק במקום למתוח אותו.

פלט: החזר אך ורק את טקסט ההודעה הסופי, מוכן לשליחה. בלי הקדמה, בלי ```, בלי הערות."""

_USER = """נתוני שוק עדכניים (Yahoo Finance, נכון לרגע זה):
{market}

חדשות עולם (מסונן, סדר לפי חשיבות):
{world}

עסקים (מסונן, סדר לפי חשיבות):
{business}

טכנולוגיה (מסונן, סדר לפי חשיבות):
{tech}

מניות בית (כותרות חדשות גולמיות לכל מניה - תחליט אתה מה משמעותי מספיק להזכיר):
{watchlist}

תאריך עברי לועזי לכותרת: {date_str}"""


def _format_items(items: list[dict]) -> str:
    if not items:
        return "(אין פריטים היום — דלג על הסעיף הזה)"
    lines = []
    for it in items:
        title   = it.get("title", "")
        source  = it.get("source", "")
        url     = it.get("url", "")
        summary = (it.get("summary") or "")[:350]
        lines.append(f"- {title} [{source}] {('| ' + url) if url else ''}\n  {summary}")
    return "\n".join(lines)


# ── Personal-style addendum (from the humanizer's style_profile.json) ──────
# Bakes the same voice/tone/vocabulary guidance humanizer.py uses for
# per-article rewrites directly into this composition's system prompt,
# instead of composing generically and rewriting after — one Claude call,
# and no risk of a second pass mangling the fixed section structure above.

def _style_addendum(profile: dict) -> str:
    v = profile.get("vocabulary", {})
    s = profile.get("sentence_structure", {})
    t = profile.get("tone", {})
    p = profile.get("patterns", {})

    banned = humanizer._BANNED_WORDS
    sig_raw   = [ph for ph in p.get("signature_phrases", []) if not any(b in ph for b in banned)]
    slang_raw = [w for w in v.get("slang", []) if w not in banned and not any(b in w for b in banned)]

    sig   = ", ".join(f'"{ph}"' for ph in sig_raw[:5])
    slang = ", ".join(slang_raw[:6])
    eng   = ", ".join(v.get("english_words_in_hebrew", [])[:6])
    trans = ", ".join(v.get("transition_words", [])[:5])

    examples = humanizer._filter_examples(profile.get("raw_examples", {}).get("best_50_examples", []))[:3]
    ex_str   = "\n".join(f'  • "{e}"' for e in examples)

    return f"""

⚠️ כתוב בקול האישי הספציפי הזה — לא בעברית "תקנית" גנרית:
• טון: {t.get("default", "—")} | פורמליות: {t.get("formality", "—")} | הומור: {t.get("humor_level", "—")}
• מבנה משפטים: {s.get("style", "—")}
• ביטויי חתימה (במינון, לא בכל משפט): {sig or "—"}
• סלנג טבעי (במינון): {slang or "—"}
• אנגלית בתוך עברית: {eng or "—"}
• מילות מעבר: {trans or "—"}

דוגמאות לסגנון (הטון בלבד, לא התוכן):
{ex_str or "  —"}

⛔ אסור בתכלית האיסור, גם אם מופיע למעלה: "מטורף", "מבסוט", "כסף על הרצפה", "הזדמנות פז", FOMO מכל סוג, המלצות קנייה/מכירה, פתיחה ב"חבר'ה", "אוקיי?"/"אוקי?"/"נכון?", ו-"אשכרה" יותר מפעם ביום."""


# ── Dedup review pass ────────────────────────────────────────────────────
# A single generation pass doesn't reliably self-count occurrences across a
# long structured message (seen in practice: the same top story landing in
# key points + a body section + the deep-dive — 3 places, over the 2-max
# rule). A dedicated second pass, only checking this one rule, catches what
# the first pass misses without risking the fixed section structure/style.

_DEDUP_REVIEW_SYSTEM = """אתה עורך שבודק טיוטת הודעת WhatsApp ומחפש הפרות של כלל אחד בלבד:

אף נושא/סיפור/אירוע ספציפי (גם אם מנוסח אחרת בכל פעם, או מוזכר רק כ"רקע"/"הקשר" למשהו אחר) לא יכול להופיע ביותר משני מקומות נפרדים בכל ההודעה - סופרים ביחד את ⭐ נקודות המפתח, כל סעיף (כולל "שווקים - מה זז באמת"), וה"לקריאה מעמיקה", כל אחד מהם נחשב "מקום". ברירת המחדל היא מקום אחד; שני מקומות מותר רק לנושא המרכזי ביותר של היום. גם אזכור חלקי/עקיף (למשל "בגלל קריאות ההאטה ב-AI" בתוך סעיף אחר) נחשב הופעה.

שלב 1 - ניתוח (כתוב את זה קודם, זה חלק מהתשובה):
רשום רשימה של כל נושא מרכזי בהודעה, ולידו בכמה "מקומות" הוא מופיע (פרט את שמות הסעיפים). לדוגמה:
- "קריאה להאטת AI ע"י מנכ"לים": נקודות מפתח, שווקים-מה-זז, לקריאה מעמיקה → 3 מקומות ⚠️ הפרה
- "סגירת צינור הנפט הסעודי": עולם, עסקים → 2 מקומות, מותר (נושא מרכזי)

שלב 2 - תיקון:
לכל נושא עם 3+ מקומות: השאר רק 2 (את המקום עם הפרטים העשירים ביותר, ואת נקודות המפתח אם היא אחת מהם), ומחק לגמרי את שאר ההופעות - כולל השורה/הבולט/האזכור העקיף כולו. אם המחיקה משאירה סעיף ריק לגמרי - מחק את כותרת הסעיף גם.
אל תשנה שום דבר אחר - לא ניסוח, לא סגנון, לא נושאים אחרים שלא הופרו.

בסוף התשובה, אחרי השלבים למעלה, כתוב בדיוק את השורה:
===FINAL===
ואחריה ההודעה הסופית המתוקנת (או ההודעה המקורית ללא שינוי אם לא הייתה הפרה) - טקסט מוכן לשליחה, בלי הסברים נוספים אחרי זה."""


async def _dedup_review(client: anthropic.AsyncAnthropic, text: str) -> str:
    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=_DEDUP_REVIEW_SYSTEM,
        messages=[{"role": "user", "content": text}],
    )
    stats.record(response.usage.input_tokens, response.usage.output_tokens)
    raw = response.content[0].text.strip()

    marker = "===FINAL==="
    if marker in raw:
        reviewed = raw.split(marker, 1)[1].strip()
    else:
        # Model didn't follow the marker format — fall back to the original
        # text rather than risking the analysis prose leaking into the send.
        print("  [morning_brief_composer] ⚠ Dedup review: no ===FINAL=== marker — keeping pre-review text")
        return text

    if reviewed.startswith("```"):
        reviewed = reviewed.split("\n", 1)[1]
        if reviewed.rstrip().endswith("```"):
            reviewed = reviewed.rstrip()[:-3]
    return reviewed.strip()


async def compose_morning_brief(digest: dict, market_text: str, watchlist_text: str) -> str:
    now      = datetime.now(_ISRAEL_TZ)
    date_str = now.strftime("%d.%m.%Y")

    profile = humanizer.load_profile()
    system  = _SYSTEM_BASE + (_style_addendum(profile) if profile else "")

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    user = _USER.format(
        market=market_text,
        world=_format_items(digest.get("world", [])),
        business=_format_items(digest.get("business", [])),
        tech=_format_items(digest.get("tech", [])),
        watchlist=watchlist_text,
        date_str=date_str,
    )

    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=3072,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    stats.record(response.usage.input_tokens, response.usage.output_tokens)

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    text = text.strip()

    text = await _dedup_review(client, text)

    # Fixed opener/closer lines, added in code (not left to the model) so
    # they're always exactly this, every time.
    text = "בוקר טוב :)\n" + text + "\n\n——\nשיהיה לכם אחלה יום ותשקיעו בהיגיון בריא- ליעוז"

    # Force right-alignment per line regardless of what character it starts with.
    text = "\n".join(_RLM + line if line else line for line in text.split("\n"))
    return text
