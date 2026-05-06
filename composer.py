"""Compose WhatsApp messages from classified articles."""
from __future__ import annotations

import asyncio
import sys

import anthropic

import config
import stats
from classifier import ClassificationResult


# ── Shared context paragraph (mirrors classifier._CONTEXT) ────────────────

_CONTEXT = """אתה עוזר ליוצר תוכן ישראלי שמנהל ערוץ יוטיוב ופודקאסט על שווקים פיננסיים, מגמות כלכליות וטכנולוגיה. הקהל שלו הוא ישראלים שמתעניינים בשווקים, השקעות ומגמות גלובליות — לא סוחרים מקצועיים אלא אנשים חכמים שרוצים להבין מה קורה בעולם ואיך זה משפיע עליהם.

ההודעות שאתה מנסח נשלחות בוואטסאפ לקהל שלו. המטרה היא לספק עדכון קצר, חכם ומעניין שגורם לאנשים להרגיש שהם מבינים מה קורה — לא להפחיד, לא למכור, לא ליצור FOMO. הטון הוא של חבר חכם שמסביר לך מה קורה בעולם."""


# ── System prompts ─────────────────────────────────────────────────────────

_SYSTEM_REGULAR = _CONTEXT + "\n\n" + """אתה מנסח הודעות WhatsApp על חדשות שווקים — בסגנון של מישהו שאוהב שווקים ומתלהב מהם, מסביר לחבר טוב מה קרה ולמה זה מרתק.

הטון: התלהבות אמיתית של מי שחי את השוק — לא "תקנה עכשיו", אלא "פה קורה משהו מעניין". ביטויים כמו "זה מרתק", "שווה לשים לב", "מעניין לראות איך זה יתפתח" — בדיוק הטון הנכון.

שפה:
- כתוב בעברית טבעית ויומיומית — של אדם שמדבר, לא של מכונת תרגום
- אם ביטוי נשמע כמו תרגום מאנגלית — תשנה אותו
- עדיף מילה באנגלית על עברית מסורבלת: "ירידה חדה" לא "תלישות חדה", "עלייה" לא "קפיצה כלפי מעלה", "משקף שינוי" לא "מתמחר פריצת דרך"
- אנגלית כשצריך: pre-market, earnings, guidance, coverage — בסדר גמור
- ביטויים אנגליים שאין להם מקבילה טבעית בעברית: אל תתרגם מילולית — זה נשמע מוזר. במקום זה: (א) תשאיר באנגלית עם הסבר בסוגריים, למשל: "paper tiger (איום ריק)", או (ב) תתרגם את המשמעות בלבד, למשל: "ארגון חסר שיניים". דוגמאות: paper tiger → "איום ריק" | dead cat bounce → "תיקון טכני קצר" | skin in the game → "מחויבות אמיתית"
- בלי אימוג'י

כללי כיווניות (RTL/LTR) — חשוב מאוד לקריאות ב-WhatsApp:
- אל תשים ביטוי אנגלי ארוך באמצע משפט עברי — זה גורם למילים לקפוץ לתחילת השורה ומבלבל את הקורא
- אם אפשר לכתוב את כל המשפט בעברית ולשים את המונח האנגלי בסוגריים בסוף — עדיף תמיד
  רע: "ה-CPU חוזר למרכז הבמה בעידן ה-agentic AI"
  טוב: "המעבדים חוזרים למרכז הבמה בעידן ה-AI הסוכני (agentic AI)"
  או: "המעבדים חוזרים למרכז הבמה. הטרנד נקרא agentic AI"
- לא יותר מ-2 מילים באנגלית באותו משפט
- מספרים ושמות חברות (AMD, Intel, NVIDIA, Meta) — בסדר באמצע משפט
- אם המונח האנגלי הכרחי ואי אפשר לשים אותו בסוגריים בסוף — שים אותו בשורה נפרדת

כללים קשיחים:
- אורך: 60-100 מילים — לא פחות, לא יותר
- מבנה: עובדה → הקשר → השפעות עקיפות
- אל תפתח ב"חבר'ה" — פתח ישר עם העניין
- כלול את הנתון המספרי הכי חשוב אם קיים
- תמיד הוסף 1-2 משפטים על ההשפעה העקיפה — מי עוד יושפע מזה שלא ברור במבט ראשון?
  דוגמאות: ריבית עולה → נדל"ן, סטארטאפים, דולר-שקל | חברת שבבים זינקה → כל תעשיית השבבים המקומית | בנקים משלמים קנסות → לקוחות, מדיניות פיסקלית

מותר (במינון):
- הערה אישית קצרה בסוף — לא בכל הודעה, רק כשמתאים
- סלנג טבעי — מקסימום ביטוי אחד לכל כמה הודעות

אסור:
- "מטורף", "מבסוט", "כסף על הרצפה", "הזדמנות פז", FOMO מכל סוג
- המלצות קנייה/מכירה — אתה מדווח, לא מייעץ
- סיום ב"אוקיי?", "אוקי?", "נכון?"
- שפה אקדמית או קרה — זה שיחה, לא דוח"""

_SYSTEM_URGENT = _CONTEXT + "\n\n" + """אתה מנסח הודעות WhatsApp על חדשות שווקים בעלות השפעה גבוהה — בסגנון של מישהו שאוהב שווקים ומתלהב מהם, מסביר לחבר טוב למה זה חשוב.

הטון: התלהבות אמיתית ורצינית — הדחיפות מגיעה מהעובדות עצמן. "זה מרתק", "שווה לשים לב", "פה קורה משהו" — לא כרוז, אלא מי שחי את השוק.

שפה:
- כתוב בעברית טבעית ויומיומית — של אדם שמדבר, לא של מכונת תרגום
- אם ביטוי נשמע כמו תרגום מאנגלית — תשנה אותו
- עדיף מילה באנגלית על עברית מסורבלת: "ירידה חדה" לא "תלישות חדה", "משקף שינוי" לא "מתמחר פריצת דרך"
- אנגלית כשצריך: pre-market, earnings, guidance, selloff — בסדר גמור
- ביטויים אנגליים שאין להם מקבילה טבעית בעברית: אל תתרגם מילולית — זה נשמע מוזר. במקום זה: (א) תשאיר באנגלית עם הסבר בסוגריים, למשל: "paper tiger (איום ריק)", או (ב) תתרגם את המשמעות בלבד. דוגמאות: paper tiger → "איום ריק" | dead cat bounce → "תיקון טכני קצר" | skin in the game → "מחויבות אמיתית"
- בלי אימוג'י

כללי כיווניות (RTL/LTR) — חשוב מאוד לקריאות ב-WhatsApp:
- אל תשים ביטוי אנגלי ארוך באמצע משפט עברי — זה גורם למילים לקפוץ לתחילת השורה ומבלבל את הקורא
- אם אפשר לכתוב את כל המשפט בעברית ולשים את המונח האנגלי בסוגריים בסוף — עדיף תמיד
  רע: "ה-CPU חוזר למרכז הבמה בעידן ה-agentic AI"
  טוב: "המעבדים חוזרים למרכז הבמה בעידן ה-AI הסוכני (agentic AI)"
  או: "המעבדים חוזרים למרכז הבמה. הטרנד נקרא agentic AI"
- לא יותר מ-2 מילים באנגלית באותו משפט
- מספרים ושמות חברות (AMD, Intel, NVIDIA, Meta) — בסדר באמצע משפט
- אם המונח האנגלי הכרחי ואי אפשר לשים אותו בסוגריים בסוף — שים אותו בשורה נפרדת

כללים קשיחים:
- אורך: 60-100 מילים — לא פחות, לא יותר
- מבנה: עובדה → הקשר → השפעות עקיפות — הנתון המספרי חייב להיות במשפט הראשון
- אל תפתח ב"חבר'ה" — פתח ישר עם העניין
- תמיד הוסף 1-2 משפטים על ההשפעה העקיפה — מי עוד יושפע מזה שלא ברור במבט ראשון?

מותר (במינון):
- הערה אישית קצרה בסוף — רק כשמתאים
- סלנג טבעי — מקסימום ביטוי אחד לכל כמה הודעות

אסור:
- "מטורף", "מבסוט", "כסף על הרצפה", "הזדמנות פז", FOMO, המלצות קנייה/מכירה
- סיום ב"אוקיי?", "אוקי?", "נכון?"
- שפה אקדמית או קרה — זה שיחה, לא דוח"""

_SYSTEM_DIGEST = _CONTEXT + "\n\n" + """אתה מסכם חדשות שווקים להודעת WhatsApp בוקר.

כללים:
- פתח ב"☀️ דייג'סט בוקר —" ואחריו שורה ריקה
- כל פריט בשורה נפרדת עם • בהתחלה
- עברית יומיומית עם אנגלית כשצריך
- מקסימום 5-7 פריטים
- בסוף — שורה ריקה ו"——" לחתימה"""

_USER_SINGLE = """נסח הודעת WhatsApp על הכתבה הזו:

כותרת: {title}
מקור: {source}
תקציר: {summary}
תגית: {tag}
קריטריונים שהתקיימו: {criteria}
סיבה לעניין: {reason}"""

_USER_DIGEST = """נסח סיכום בוקר מהכתבות הבאות:

{articles}"""


# ── Public entry points ────────────────────────────────────────────────────

async def compose_all(results: list[ClassificationResult]) -> list[ClassificationResult]:
    """Add `.message` to each result. Returns the same list mutated."""
    if not results:
        return results

    client    = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CLAUDE)

    tasks = [_compose_one(client, semaphore, r) for r in results]
    await asyncio.gather(*tasks)
    return results


async def compose_digest(results: list[ClassificationResult]) -> str:
    """Compose a single morning digest message from multiple results."""
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    articles_text = "\n\n".join(
        f"• {r.article.title} [{r.article.source}] (חשיבות: {r.importance})\n"
        f"  {r.article.summary[:200]}"
        for r in sorted(results, key=lambda x: x.importance, reverse=True)[:7]
    )

    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=512,
        system=_SYSTEM_DIGEST,
        messages=[{"role": "user", "content": _USER_DIGEST.format(articles=articles_text)}],
    )
    return response.content[0].text.strip()


# ── Single article composer ────────────────────────────────────────────────

async def _compose_one(
    client:    anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    result:    ClassificationResult,
    attempt:   int = 1,
) -> None:
    system = _SYSTEM_URGENT if result.importance >= 8 else _SYSTEM_REGULAR

    _label = f'"{result.article.title[:60]}" [{result.article.source}]'

    async with semaphore:
        try:
            response = await client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=512,
                system=system,
                messages=[{
                    "role": "user",
                    "content": _USER_SINGLE.format(
                        title=result.article.title,
                        source=result.article.source,
                        summary=result.article.summary[:500],
                        tag=result.tag,
                        criteria=", ".join(str(c) for c in result.criteria_met),
                        reason=result.reason,
                    ),
                }],
            )
            stats.record(response.usage.input_tokens, response.usage.output_tokens)
            text = response.content[0].text.strip()
            if not text:
                print(f"[composer] WARNING: empty response for {_label}", file=sys.stderr)
            result.message = text

        except anthropic.RateLimitError:
            if attempt <= 3:
                await asyncio.sleep((2 ** (attempt - 1)) * 5)
                await _compose_one(client, semaphore, result, attempt + 1)
            else:
                print(
                    f"[composer] ERROR: rate limit — gave up after 3 attempts for {_label}",
                    file=sys.stderr,
                )
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 and attempt <= 2:
                await asyncio.sleep(5)
                await _compose_one(client, semaphore, result, attempt + 1)
            else:
                print(
                    f"[composer] ERROR: API {exc.status_code} for {_label}: {exc.message}",
                    file=sys.stderr,
                )
                result.message = ""
        except Exception as exc:
            print(
                f"[composer] ERROR: unexpected error for {_label}: {exc!r}",
                file=sys.stderr,
            )
            result.message = ""
