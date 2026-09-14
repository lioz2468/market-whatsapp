"""Compose the daily morning brief as a WhatsApp message (plain text, WhatsApp's
own *bold*/_italic_ formatting — no HTML) from email_digest.json + a market
snapshot, using Claude. Separate from composer.py (per-article WhatsApp
messages) and newsletter_composer.py (parked HTML/email version) — same
separation principle as email_classifier.py vs classifier.py. Used only by
send_morning_brief.py.
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

אתה כותב "בריף בוקר" יומי — הודעת WhatsApp שנשלחת לקבוצת נרשמים. זו הודעת טקסט רגילה (לא מייל, לא HTML) — אפשר להשתמש בעיצוב הטבעי של WhatsApp: כוכבית אחת משני צדי מילה ל*הדגשה*, קו תחתון ל_נטוי_, בלי שום תגיות HTML או markdown של #/**.

מבנה חובה, בסדר הזה, עם שורה ריקה בין סעיפים:
1. שורה ראשונה: "☀️ *בריף בוקר* — {תאריך}"
2. ⭐ 3 נקודות מפתח — שורה אחת כל אחת, כל שורה מתחילה ב-•
3. *תמונת מצב שוקים* — 4-6 שורות, כל שורה: שם המדד = מספר + אחוז שינוי
4. *כותרות עולם* — עד 5 שורות, כל שורה מתחילה ב-•, עובדה + (מקור בסוגריים)
5. *עסקים* — עד 5 שורות, אותו פורמט
6. *טכנולוגיה* — עד 5 שורות, אותו פורמט. **אם אין פריטי טכנולוגיה בקלט — דלג על הסעיף כולו בשקט**
7. *שווקים — מה זז באמת* — רק תנועות מהותיות, 2-4 שורות
8. *לקריאה מעמיקה* — כתבה אחת, מה קרה + למה זה חשוב + קישור למקור
9. שורה אחרונה: "——" ואז שורת חתימה קצרה

טון: תמציתי מאוד. עובדה + מספר + מקור. בלי מילות מילוי, בלי "חשוב לציין", בלי המלצות קנייה/מכירה, בלי FOMO.
שמות חברות ומדדים כתובים באנגלית (S&P 500, Nasdaq, Tesla וכו').
אל תתמקד באובססיביות בחברה ספציפית אחת אלא אם היא ממש הסיפור של היום.
מקף קצר "-" בלבד, לעולם לא מקף ארוך "—" (em dash) — חוץ מקו ההפרדה "——" לפני החתימה.
אורך כולל: הודעת WhatsApp אחת קריאה, לא ארוכה מדי — לא יותר מ-40 שורות סה"כ כולל שורות ריקות.

פלט: החזר אך ורק את טקסט ההודעה הסופי, מוכן לשליחה. בלי הקדמה, בלי ```, בלי הערות."""

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


async def compose_morning_brief(digest: dict, market_text: str) -> str:
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
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    stats.record(response.usage.input_tokens, response.usage.output_tokens)

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
