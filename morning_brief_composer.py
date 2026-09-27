"""Compose the daily morning brief as a WhatsApp message (plain text, WhatsApp's
own *bold*/_italic_ formatting — no HTML) from email_digest.json + a market
snapshot + a watchlist news feed, using Claude. Separate from composer.py
(per-article WhatsApp messages) — same separation principle as
email_classifier.py vs classifier.py. Used only by send_morning_brief.py.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

import config
import humanizer
import stats
from classifier import CreditBalanceError

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
2. ⭐ 3 נקודות מפתח — שורה אחת כל אחת, כל שורה מתחילה ב-•. שלושת הסיפורים הכי חשובים של היום *מכל התחומים* (עולם/גיאופוליטיקה, כלכלה, טכנולוגיה) - לפחות אחד מהם חדשות עולם, לא רק שוק/מניות. רק מתוך ידיעות החדשות בקלט - לא מנתוני השוק (לנתוני שוק יש סעיף משלהם), ולא סיפור שכבר נשלח בבריפים קודמים. **סיפור שנכנס לכאן לא מופיע שוב בשום סעיף אחר** - לא בכותרות עולם, לא בעסקים, לא בשווקים ולא בלקריאה מעמיקה.
3. *תמונת מצב שוקים* — 4-6 שורות, כל שורה: שם המדד = מספר + אחוז שינוי. **העתק כל מספר בדיוק כפי שהוא ב"נתוני שוק עדכניים" בקלט** - לא לעגל, לא לשנות, לא לקחת מספר מכתבה. בכל ההודעה, כל מספר של מדד/תשואה/מטבע חייב להיות זהה לנתוני השוק בקלט.
4. *כותרות עולם* — עד 5 שורות, כל שורה מתחילה ב-•. עולם (חוץ-ישראל) קודם, ישראל אחרי
5. *עסקים* — עד 5 שורות, אותו סדר (עולם קודם, ישראל אחרי). **כללי-מאקרו/סקטוריאלי בלבד - לא חברה בודדת שיש לה כבר בית בסעיף 7.** **אסור בהחלט להזכיר כאן אף חברה שמופיעה ברשימת "מניות בית" למטה** (למשל אם Rocket Lab, Robinhood, FTAI Aviation או SoFi שם - אל תכתוב עליהן כאן בכלל, גם אם הידיעה "נשמעת" עסקית-כללית) - לחברות מרשימת המעקב יש בלעדית את סעיף 7, בלי שום חריג, גם לא כשזה הסיפור המרכזי של היום.
6. *טכנולוגיה* — עד 5 שורות, אותו פורמט. **אם אין פריטי טכנולוגיה בקלט — דלג על הסעיף כולו בשקט**
7. *מניות הבית* — רק אם יש עדכון *משמעותי באמת* לגבי אחת המניות ברשימה (ראה קלט "מניות בית" למטה, שכבר מסונן לחדשות עדכניות בלבד) — לא כל עדכון, רק דברים שבאמת משנים תמונה (רבעון, מהלך אסטרטגי, שינוי הנהלה, רגולציה, אירוע קיצון). מכירת מניות קטנה של בעל עניין, העלאת מחיר יעד של אנליסט וכדומה - לא משמעותי. **עד 4 מניות, שורה-שתיים לכל מניה, כותרת סעיף אחת בלבד (בלי "המשך")**. **אם אין שום עדכון משמעותי לאף מניה — דלג על הסעיף כולו בשקט, אל תכתוב "אין עדכונים"**. אל תשתמש בידע כללי/ישן שלך על המניות האלה - רק על סמך הכותרות העדכניות בקלט.
8. *שווקים - מה זז באמת* — רק תנועות מהותיות, 2-4 שורות. **אסור לחזור כאן על סיפור/קטליזטור שכבר סופר בסעיף אחר (עולם/עסקים/טכנולוגיה)** - גם לא בניסוח "תגובת השוק ל-X" או "על רקע Y" - זה עדיין אותו נושא, ראה כלל הכפילויות למטה. מותר רק נתון כמותי חדש שלא הופיע במקום אחר (רמת מחיר ספציפית, טווח, פער בין סקטורים) - לא חזרה על הרקע/הסיבה.
9. *לקריאה מעמיקה* — כתבה אחת *שלא הוזכרה בשום מקום אחר בהודעה*, מה קרה + למה זה חשוב + קישור למקור (רק כאן מותר קישור/ציון מקור מפורש) — זה הסעיף האחרון, אל תוסיף אחריו שום שורת סיום/חתימה/פתיח - אלה מתווספים באופן קבוע מחוץ להודעה שלך

כללי תוכן קריטיים:
- **ספירה קשיחה — בלי כפילויות בכל ההודעה**: לפני שאתה מסיים, ספור בעצמך כמה פעמים כל נושא/סיפור/אירוע ספציפי (למשל "מנכ"לי AI קוראים להאטה") מופיע בכל ההודעה יחד — ⭐ נקודות מפתח + כל הסעיפים + לקריאה מעמיקה, הכל ביחד. הכלל: **פעם אחת בדיוק**, בסעיף אחד בלבד - בלי שום חריג, גם לא לסיפור המרכזי של היום. דוגמה לטעות: "הסכם המכסים בין ארה"ב לסין" בנקודות מפתח, ושוב כחלק מבולט על ביקור שי בכותרות עולם, ושוב כ"הסכם הסחר עם סין עושה עבודה" בשווקים - זו טעות, צריך להופיע רק פעם אחת. אותו דבר לנתון שוק: אם תשואת ה-10Y מופיעה בתמונת מצב שוקים, אל תחזור עליה בנקודות מפתח או ב"מה זז באמת". זה חל גם כשאותו סיפור מגיע מכמה קטגוריות קלט שונות (עולם/עסקים/טכנולוגיה) — הוא עדיין נספר כנושא אחד. **תגובת שוק לסיפור שכבר סופר היא אותו נושא, לא נושא חדש**: אם "כותרות עולם" מסבירה שהריבית/התשואות עולות, ו"שווקים - מה זז באמת" כותב "מניות הצמיחה נפלו על רקע עליית התשואות" - זו אותה כותרת פעמיים, לא שני דברים. עסקים (סעיף 5) ומניות הבית (סעיף 7) אף פעם לא חולקים חברה (ראה סעיף 5).
- **רק מידע חדש - לא שכתוב של מה שהקוראים כבר יודעים**: כל בולט = מה קרה *מאז הבריף הקודם* - אירוע, החלטה, נתון, הכרזה. הקורא כבר קרא את הבריפים הקודמים (ראה "כבר נשלח בבריפים קודמים" בקלט): אל תסביר שוב רקע או מצב מתמשך שכבר מוכר (למשל "מצר הורמוז חסום", "המלחמה נמשכת", "התשואות גבוהות"). בסיפור מתמשך - כתוב רק את ההתפתחות החדשה עצמה, בלי לחזור על מה שהיה. פריט קלט שהוא ניתוח/פרשנות/סקירה ("How we got here", "What did X accomplish", "X becomes Y") בלי אירוע חדש ספציפי - דלג עליו, או השתמש רק בעובדה החדשה שבו אם יש. עדיף סעיף קצר עם 2 בולטים חדשים באמת מאשר 5 בולטים שחלקם מיחזור.
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

כבר נשלח בבריפים קודמים (הקוראים כבר יודעים את זה - לא לחזור, לא להסביר שוב, רק התפתחות חדשה אם יש):
{history}

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


# ── Cross-day dedup (against previously-sent briefs) ────────────────────────
# email_digest.json is rebuilt fresh every morning with no memory of what
# yesterday's brief actually sent (world/tech are re-classified straight
# from RSS; business is just "approved for WhatsApp in the last 24h"), and
# watchlist_news.py just re-fetches each ticker's last 48h of headlines from
# scratch — so the same story (e.g. an Anthropic/Nvidia item, or a watchlist
# company's story still circulating within that 48h window) could repeat
# across consecutive mornings undetected. This checks each candidate —
# world/business/tech items and watchlist headlines alike — against
# config.MORNING_BRIEF_HISTORY_PATH, the last MORNING_BRIEF_HISTORY_DAYS of
# what was actually included, using the same "specific new event, not just
# more coverage" rule as classifier.py's topic_dedup_filter (which does this
# for the per-article WhatsApp bot).

def _history_check_system() -> str:
    return _CONTEXT + "\n\n" + f"""אתה בודק האם ידיעה מועמדת לבריף של היום היא *אותו סיפור בדיוק* כמו אחת הידיעות הממוספרות שכבר נשלחו בבריפים של {config.MORNING_BRIEF_HISTORY_DAYS} הימים האחרונים.

"אותו סיפור" = אותו אירוע ספציפי, רק בכותרת אחרת / ניתוח נוסף / פרשנות / עוד פרטים עליו.
"סיפור חדש" = כל דבר אחר - כולל אירוע חדש ספציפי באותו נושא רחב (נתון חדש שפורסם, החלטה שהתקבלה, הכרזה רשמית, שינוי כיוון, פגישה/פסגה חדשה). נושא רחב משותף (למשל "איראן", "AI", "סין") לא הופך ידיעה לכפילות.

פורמט תשובה - אחד משניים בלבד, בלי הסבר:
- "חדש" - אם אין ידיעה ממוספרת שהיא אותו סיפור בדיוק (ברירת המחדל).
- המספר של הידיעה הקודמת שהיא אותו סיפור בדיוק (למשל "7") - רק אם אתה יכול להצביע על ידיעה ספציפית כזו."""


async def cross_day_dedup_filter(items: list[dict], history: list[dict]) -> list[dict]:
    """Drop items whose story already appeared in a recent morning brief.
    Claude must cite the specific numbered history entry the item
    duplicates; anything without a valid citation is kept. (An earlier
    yes/no version — "does it bring a specific new event?" — answered "no"
    for unrelated stories too and emptied the whole digest: 25 of 25 items
    dropped on 2026-09-27, so the brief went out with no news at all.)
    Both `items` and `history` entries need "title" and "topics"."""
    if not history or not items:
        return items

    history_context = "\n".join(
        f"{i}. {h.get('date', '')}: {h.get('title', '')} | נושאים: {', '.join(h.get('topics') or ['—'])}"
        for i, h in enumerate(history, 1)
    )

    client    = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CLAUDE)

    async def _check_one(it: dict) -> dict | None:
        async with semaphore:
            try:
                resp = await client.messages.create(
                    model=config.CLAUDE_CLASSIFIER_MODEL,
                    max_tokens=16,
                    system=_history_check_system(),
                    messages=[{"role": "user", "content":
                        f"ידיעות שכבר נשלחו:\n{history_context}\n\n"
                        f"ידיעה מועמדת: {it.get('title', '')}\n"
                        f"נושאים: {', '.join(it.get('topics') or [])}\n\n"
                        'האם זה אותו סיפור בדיוק כמו אחת הידיעות הממוספרות? ענה "חדש" או מספר.'
                    }],
                )
                stats.record(
                    resp.usage.input_tokens,
                    resp.usage.output_tokens,
                    model=config.CLAUDE_CLASSIFIER_MODEL,
                )
                answer = resp.content[0].text.strip()
            except CreditBalanceError:
                raise
            except Exception as exc:
                print(f"  [morning-brief-dedup] ⚠ Check error for '{it.get('title', '')[:40]}': {exc}")
                return it

        m = re.match(r"\s*(\d+)", answer)
        if m and 1 <= int(m.group(1)) <= len(history):
            dup = history[int(m.group(1)) - 1]
            print(
                f"  [morning-brief-dedup] ⏭ Skipping '{it.get('title', '')[:55]}' "
                f"— same as {dup.get('date', '')}: '{dup.get('title', '')[:55]}'"
            )
            return None
        return it

    tasks   = [_check_one(it) for it in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[dict] = []
    for r in results:
        if isinstance(r, CreditBalanceError):
            raise r
        if isinstance(r, Exception):
            print(f"  [morning-brief-dedup] ⚠ Unexpected error: {r}")
        elif r is not None:
            out.append(r)
    return out


# ── Dedup review pass ────────────────────────────────────────────────────
# A single generation pass doesn't reliably self-count occurrences across a
# long structured message (seen in practice: the same top story landing in
# key points + a body section + the deep-dive). The rule is now "each story
# in exactly one place" — the earlier "twice allowed for the top story"
# exception still produced 3-place repeats. A dedicated second pass, only checking this one rule, catches what
# the first pass misses without risking the fixed section structure/style.

_DEDUP_REVIEW_SYSTEM = """אתה עורך שבודק טיוטת הודעת WhatsApp ומחפש הפרות של שני כללים:

כלל א' (מקום אחד בלבד): כל נושא/סיפור/אירוע/נתון ספציפי (גם אם מנוסח אחרת בכל פעם, או מוזכר רק כ"רקע"/"הקשר" למשהו אחר, כולל ניסוח "תגובת שוק" כמו "מניות X ירדו על רקע Y") מופיע במקום אחד בלבד בכל ההודעה - סופרים ביחד את ⭐ נקודות המפתח, כל סעיף (כולל "שווקים - מה זז באמת"), וה"לקריאה מעמיקה", כל אחד מהם נחשב "מקום". אין חריג - גם לא לנושא המרכזי של היום. (שורת מדד ב"תמונת מצב שוקים" עצמה היא נתון גולמי ולא נספרת, אבל אם אותו מדד/תשואה מוזכר גם בנקודות מפתח או ב"מה זז באמת" - זו הפרה.) גם אזכור חלקי/עקיף (למשל "בגלל קריאות ההאטה ב-AI" בתוך סעיף אחר, או "שווקים - מה זז באמת" שמסביר תוצאה של סיפור שכבר סופר ב"כותרות עולם"/"עסקים") נחשב הופעה - לא נושא חדש.

כלל ב' (עסקים ≠ מניות הבית, בלי יוצא מן הכלל): אם חברה כלשהי מוזכרת גם בסעיף "עסקים" וגם בסעיף "מניות הבית" - זו תמיד הפרה, גם אם זה רק 2 מקומות וגם אם זה "הנושא המרכזי של היום". חברה ששייכת לרשימת המעקב (מוזכרת ב"מניות הבית") אסורה לחלוטין בסעיף "עסקים" - אין שום תרחיש שבו זה מותר.

שלב 1 - ניתוח (כתוב את זה קודם, זה חלק מהתשובה):
רשום רשימה של כל נושא מרכזי בהודעה, ולידו בכמה "מקומות" הוא מופיע (פרט את שמות הסעיפים), וסמן אם מדובר בחברה שמופיעה גם ב"מניות הבית". לדוגמה:
- "הסכם מכסים ארה"ב-סין": נקודות מפתח, כותרות עולם (בתוך בולט על ביקור שי), שווקים-מה-זז ("הסכם הסחר עם סין עושה עבודה") → 3 מקומות ⚠️ הפרת כלל א'
- "OpenAI עצרה אימון מודלים": נקודות מפתח, לקריאה מעמיקה → 2 מקומות ⚠️ הפרת כלל א'
- "Kalshi - פסיקת ערעור": עסקים → מקום אחד, תקין
- "Rocket Lab גייסה מימון לעסקת Iridium": עסקים, מניות הבית → ⚠️ הפרת כלל ב'
- "עליית תשואות האג"ח" בנקודות מפתח ו"תשואת ה-10Y חצתה 5%" ב"שווקים - מה זז באמת" → 2 מקומות ⚠️ הפרת כלל א'

שלב 2 - תיקון:
לכל הפרת כלל א': השאר את הנושא במקום אחד בלבד ומחק את כל שאר ההופעות. איזה מקום להשאיר: אם אחת ההופעות בנקודות המפתח - השאר שם ומחק מהגוף ומ"מה זז באמת". אם אחת ההופעות ב"לקריאה מעמיקה" (ולא בנקודות מפתח) - השאר שם. אם נקודות מפתח וגם לקריאה מעמיקה - השאר את לקריאה מעמיקה, ובנקודות המפתח החלף את השורה בסיפור חשוב אחר מתוך גוף ההודעה (והעבר אותו: מחק את הבולט שלו מהגוף). אם נשארו פחות מ-3 נקודות מפתח - זה בסדר.
לכל הפרת כלל ב': מחק את ההופעה בסעיף "עסקים" לגמרי (השאר רק ב"מניות הבית").
בשני המקרים: מחק את השורה/הבולט/האזכור העקיף כולו, לא רק חלק ממנו. אם המחיקה משאירה סעיף ריק לגמרי - מחק את כותרת הסעיף גם.
אל תשנה שום דבר אחר - לא ניסוח, לא סגנון, לא מספרים, לא נושאים אחרים שלא הופרו.

בסוף התשובה, אחרי השלבים למעלה, כתוב בדיוק את השורה:
===FINAL===
ואחריה ההודעה הסופית המתוקנת (או ההודעה המקורית ללא שינוי אם לא הייתה הפרה) - טקסט מוכן לשליחה, בלי הסברים נוספים אחרי זה."""


async def _dedup_review(client: anthropic.AsyncAnthropic, text: str) -> str:
    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=8192,
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


async def compose_morning_brief(
    digest: dict, market_text: str, watchlist_text: str, history: list[dict] | None = None,
) -> str:
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
        history="\n".join(f"- {h.get('date', '')}: {h.get('title', '')}" for h in history or []) or "(אין)",
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
