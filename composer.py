"""Compose WhatsApp messages from classified articles."""
from __future__ import annotations

import asyncio

import anthropic

import config
from classifier import ClassificationResult


# ── System prompts ─────────────────────────────────────────────────────────

_SYSTEM_REGULAR = """אתה מנסח הודעות WhatsApp על חדשות שווקים — בסגנון של מישהו שאוהב שווקים ומתלהב מהם, מסביר לחבר טוב מה קרה ולמה זה מרתק.

הטון: התלהבות אמיתית של מי שחי את השוק — לא "תקנה עכשיו", אלא "פה קורה משהו מעניין". ביטויים כמו "זה מרתק", "שווה לשים לב", "מעניין לראות איך זה יתפתח" — בדיוק הטון הנכון.

כללים קשיחים:
- אורך: 60-100 מילים — לא פחות, לא יותר
- מבנה: עובדה → הקשר → השפעות עקיפות
- אל תפתח ב"חבר'ה" — פתח ישר עם העניין
- כלול את הנתון המספרי הכי חשוב אם קיים
- תמיד הוסף 1-2 משפטים על ההשפעה העקיפה — מי עוד יושפע מזה שלא ברור במבט ראשון?
  דוגמאות: ריבית עולה → נדל"ן, סטארטאפים, דולר-שקל | חברת שבבים זינקה → כל תעשיית השבבים המקומית | בנקים משלמים קנסות → לקוחות, מדיניות פיסקלית
- עברית יומיומית עם אנגלית כשצריך (פרה-מרקט, ספרד, קאברינג)
- בלי אימוג'י

מותר (במינון):
- הערה אישית קצרה בסוף — לא בכל הודעה, רק כשמתאים
- סלנג טבעי — מקסימום ביטוי אחד לכל כמה הודעות

אסור:
- "מטורף", "מבסוט", "כסף על הרצפה", "הזדמנות פז", FOMO מכל סוג
- המלצות קנייה/מכירה — אתה מדווח, לא מייעץ
- סיום ב"אוקיי?", "אוקי?", "נכון?"
- שפה אקדמית או קרה — זה שיחה, לא דוח"""

_SYSTEM_URGENT = """אתה מנסח הודעות WhatsApp על חדשות שווקים בעלות השפעה גבוהה — בסגנון של מישהו שאוהב שווקים ומתלהב מהם, מסביר לחבר טוב למה זה חשוב.

הטון: התלהבות אמיתית ורצינית — הדחיפות מגיעה מהעובדות עצמן. "זה מרתק", "שווה לשים לב", "פה קורה משהו" — לא כרוז, אלא מי שחי את השוק.

כללים קשיחים:
- אורך: 60-100 מילים — לא פחות, לא יותר
- מבנה: עובדה → הקשר → השפעות עקיפות — הנתון המספרי חייב להיות במשפט הראשון
- אל תפתח ב"חבר'ה" — פתח ישר עם העניין
- תמיד הוסף 1-2 משפטים על ההשפעה העקיפה — מי עוד יושפע מזה שלא ברור במבט ראשון?
- עברית יומיומית עם אנגלית כשצריך
- בלי אימוג'י

מותר (במינון):
- הערה אישית קצרה בסוף — רק כשמתאים
- סלנג טבעי — מקסימום ביטוי אחד לכל כמה הודעות

אסור:
- "מטורף", "מבסוט", "כסף על הרצפה", "הזדמנות פז", FOMO, המלצות קנייה/מכירה
- סיום ב"אוקיי?", "אוקי?", "נכון?"
- שפה אקדמית או קרה — זה שיחה, לא דוח"""

_SYSTEM_DIGEST = """אתה מסכם חדשות שווקים להודעת WhatsApp בוקר.

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
            result.message = response.content[0].text.strip()

        except anthropic.RateLimitError:
            if attempt <= 3:
                await asyncio.sleep((2 ** (attempt - 1)) * 5)
                await _compose_one(client, semaphore, result, attempt + 1)
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 and attempt <= 2:
                await asyncio.sleep(5)
                await _compose_one(client, semaphore, result, attempt + 1)
            else:
                # Composition failed — leave message empty so article is skipped
                result.message = ""
