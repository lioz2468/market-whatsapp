"""Compose the full HTML newsletter body from email_digest.json + a market
snapshot, using Claude. Entirely separate from composer.py (WhatsApp) — same
separation principle as email_classifier.py vs classifier.py. Used only by
send_newsletter.py.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

import config
import stats

_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


# ── Context (mirrors composer._CONTEXT / classifier._CONTEXT) ──────────────

_CONTEXT = """אתה עוזר ליוצר תוכן ישראלי שמנהל ערוץ יוטיוב ופודקאסט על שווקים פיננסיים, מגמות כלכליות וטכנולוגיה. הקהל שלו הוא ישראלים שמתעניינים בשווקים, השקעות ומגמות גלובליות — לא סוחרים מקצועיים אלא אנשים חכמים שרוצים להבין מה קורה בעולם ואיך זה משפיע עליהם."""


# ── System prompt ────────────────────────────────────────────────────────

_SYSTEM = _CONTEXT + """

אתה כותב "בריף בוקר" יומי — ניוזלטר במייל שנשלח לנרשמים בעברית, RTL. זה לא הודעת וואטסאפ — זה מייל שלם עם מבנה קבוע.

מבנה חובה, בסדר הזה:
1. כותרת ראשית: "בריף בוקר — {תאריך}"
2. ⭐ 3 נקודות מפתח — שורה אחת כל אחת, התמצית של היום
3. תמונת מצב שוקים — 4-6 שורות, כל שורה: שם המדד = מספר + אחוז שינוי
4. כותרות עולם — עד 5 שורות, כל שורה: עובדה + מקור באפור קטן
5. עסקים — עד 5 שורות, אותו פורמט
6. טכנולוגיה — עד 5 שורות, אותו פורמט. **אם אין פריטי טכנולוגיה בקלט — דלג על הסעיף כולו בשקט, בלי להתנצל ובלי לציין שהוא חסר**
7. שווקים — מה זז באמת — רק תנועות מהותיות, לא כל מספר
8. סיפור לקריאה מעמיקה — כתבה אחת, מה קרה + למה זה חשוב היום + קישור למקור

טון: תמציתי מאוד. עובדה + מספר + מקור. בלי מילות מילוי, בלי "חשוב לציין", בלי המלצות קנייה/מכירה, בלי FOMO.
שמות חברות ומדדים כתובים באנגלית (S&P 500, Nasdaq, Tesla וכו').
אל תתמקד באובססיביות בחברה ספציפית אחת אלא אם היא ממש הסיפור של היום.
מקף קצר "-" בלבד, לעולם לא מקף ארוך "—" (em dash).

פורמט פלט — קריטי:
החזר אך ורק HTML מלא ותקין, בלי שום דבר לפניו או אחריו (בלי הקדמה, בלי ```html, בלי הערות).
RTL מלא: <html dir="rtl" lang="he"> ו-style="direction:rtl; text-align:right" על גוף הטקסט.
עיצוב inline (style="..." על כל אלמנט) כדי שיעבוד נכון בלקוחות מייל — בלי <style> חיצוני, בלי CSS classes, בלי JavaScript, בלי תמונות חיצוניות.
רוחב מקסימלי ~600px, פונט קריא (Arial/Helvetica), רקע בהיר, כותרות מודגשות, מקורות באפור קטן (#888 בערך).
בסוף המייל — שורת הפרדה ושורת פוטר קטנה עם שם השולח ואת המשפט: "לביטול המנוי, השב/י למייל זה." (מנגנון ההסרה בפועל מתווסף על ידי רב מסר אוטומטית, השורה הזו רק לשקיפות)."""

_USER = """נתוני שוק עדכניים (Yahoo Finance, נכון לרגע זה):
{market}

חדשות עולם (מסונן, סדר לפי חשיבות):
{world}

עסקים (מסונן, סדר לפי חשיבות):
{business}

טכנולוגיה (מסונן, סדר לפי חשיבות):
{tech}

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


async def compose_newsletter(digest: dict, market_text: str) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    now      = datetime.now(_ISRAEL_TZ)
    date_str = now.strftime("%d.%m.%Y")

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    user = _USER.format(
        market=market_text,
        world=_format_items(digest.get("world", [])),
        business=_format_items(digest.get("business", [])),
        tech=_format_items(digest.get("tech", [])),
        date_str=date_str,
    )

    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    stats.record(response.usage.input_tokens, response.usage.output_tokens)

    html_body = response.content[0].text.strip()
    if html_body.startswith("```"):
        html_body = html_body.split("\n", 1)[1]
        if html_body.rstrip().endswith("```"):
            html_body = html_body.rstrip()[:-3]
    html_body = html_body.strip()

    subject = f"בריף בוקר — {date_str}"
    return subject, html_body
