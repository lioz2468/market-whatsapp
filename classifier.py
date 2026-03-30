"""Async article classifier using Claude API with exponential-backoff retry."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

import anthropic

import config
from feeds import Article


# ── Result model ───────────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    article:       Article
    approved:      bool
    criteria_met:  list[int]
    reason:        str
    tag:           str         # ארה"ב | ישראל | גלובלי
    importance:    int         # 1–10
    topics:        list[str] = field(default_factory=list)  # e.g. ["פד", "ריבית"]
    message:       str = ""           # filled by composer
    humanized_msg: str = ""           # filled by humanizer

    @property
    def final_message(self) -> str:
        return self.humanized_msg or self.message


# ── System prompt (classification criteria) ────────────────────────────────

_SYSTEM = """אתה מסנן כתבות חדשות כלכליות-פיננסיות לניוזלטר השקעות.

כתבה עוברת אם היא עונה על לפחות 3 מתוך 15 הקריטריונים הבאים:

1.  השפעה מוחשית על המציאות — שינוי מהותי שמשפיע ישירות על חיי היומיום או תעשיות מרכזיות
2.  גיבוי בנתוני מאקרו — מבוסס על נתונים כלכליים קונקרטיים (דמוגרפיה, שוק תעסוקה), לא תחזיות מעורפלות
3.  שיבוש תעשיות מסורתיות — טכנולוגיה חדשה או שינוי התנהגותי שמאלצים מודלים עסקיים ותיקים להשתנות
4.  טריגר רגולטורי מובהק — חקיקה חדשה או תקציבי עתק ציבוריים שמייצרים רוח גבית קונקרטית
5.  השפעה רוחבית — התופעה מייצרת גלי הדף על מספר סקטורים
6.  תמורות בשרשראות אספקה — שינויים פיזיים ומדידים בנתיבי סחר גלובליים או מרכזי ייצור
7.  שינוי בהתנהגות צרכנים — עדות עובדתית לשינוי בהרגלי הוצאות או צריכת זמן
8.  השקעות עתק בתשתיות — שדרוג פיזי עתיר הון (חוות שרתים, רשתות חשמל, כבלי תקשורת)
9.  מיפוי מרוויחים ומפסידים — מציג אובייקטיבית גם מי ירוויח וגם מי ייפגע
10. פתרון צווארי בקבוק גלובליים — מענה מעשי לנקודת כאב בוערת (מחסור בכוח אדם, אבטחת מידע)
11. אימוץ מוסדי נרחב — מעבר ברור מ-Early Adopters לאימוץ המוני ע"י תאגידי ענק
12. ניסוח נטול יח"צ — ניתוח קונקרטי, לא הייפ או כותרות סנסציוניות
13. מבנה יסודי מול טרנד חולף — הסבר מנומק למה זה שינוי מבני ארוך טווח
14. מעקב אחר זרימת ההון — נתונים עובדתיים על לאן קרנות הון סיכון וכסף מוסדי זורמים
15. פוטנציאל סיפורי ברור — המגמה מוגדרת היטב ואפשר לזקק ממנה סיפור ברור שיעורר שיח

כתבה נדחית אם היא:
- ידיעה כללית ללא השפעה ישירה
- כתבת דעה שגרתית / ניתוח שטחי
- הייפ ויח"צ בלי תוכן מהותי
- ספורט, פוליטיקה ללא קשר לכלכלה, רכילות

ענה בפורמט הבא בדיוק (6 שורות, ללא טקסט נוסף):
החלטה: כן / לא
קריטריונים שהתקיימו: 1, 5, 14
סיבה: [משפט אחד]
תגית: ארה"ב / ישראל / גלובלי
דירוג חשיבות: [1-10]
נושאים: [עד 4 תגיות נושא מופרדות בפסיק, למשל: פד, ריבית, אנבידיה, תקציב]"""

_USER_TMPL = """כותרת: {title}
מקור: {source}
תקציר: {summary}"""


# ── Public entry points ────────────────────────────────────────────────────

async def classify_all(articles: list[Article]) -> list[ClassificationResult]:
    """Classify articles concurrently, respecting MAX_CONCURRENT_CLAUDE."""
    if not articles:
        return []

    client    = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CLAUDE)

    tasks = [_classify_one(client, semaphore, article) for article in articles]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out = []
    for r in results:
        if isinstance(r, Exception):
            print(f"  [classifier] ⚠ Classification error: {r}")
        else:
            out.append(r)
    return out


# ── Single article ─────────────────────────────────────────────────────────

async def _classify_one(
    client:    anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    article:   Article,
) -> ClassificationResult:
    async with semaphore:
        raw = await _call_claude(client, article)
    return _parse(raw, article)


async def _call_claude(
    client:  anthropic.AsyncAnthropic,
    article: Article,
    attempt: int = 1,
    max_retries: int = 4,
) -> str:
    try:
        response = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=256,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": _USER_TMPL.format(
                    title=article.title,
                    source=article.source,
                    summary=article.summary[:600],
                ),
            }],
        )
        return response.content[0].text

    except anthropic.RateLimitError:
        if attempt < max_retries:
            wait = (2 ** (attempt - 1)) * 5   # 5, 10, 20, 40 s
            print(f"  [classifier] Rate limited — retrying in {wait}s…")
            await asyncio.sleep(wait)
            return await _call_claude(client, article, attempt + 1, max_retries)
        raise

    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500 and attempt < max_retries:
            wait = (2 ** (attempt - 1)) * 3
            await asyncio.sleep(wait)
            return await _call_claude(client, article, attempt + 1, max_retries)
        raise


# ── Response parser ────────────────────────────────────────────────────────

_DECISION_RE   = re.compile(r"החלטה:\s*(כן|לא)", re.I)
_CRITERIA_RE   = re.compile(r"קריטריונים שהתקיימו:\s*([\d,\s]+)")
_REASON_RE     = re.compile(r"סיבה:\s*(.+)")
_TAG_RE        = re.compile(r"תגית:\s*(ארה\"ב|ישראל|גלובלי)")
_IMPORTANCE_RE = re.compile(r"דירוג חשיבות:\s*(\d+)")
_TOPICS_RE     = re.compile(r"נושאים:\s*(.+)")


def _parse(raw: str, article: Article) -> ClassificationResult:
    decision_m   = _DECISION_RE.search(raw)
    criteria_m   = _CRITERIA_RE.search(raw)
    reason_m     = _REASON_RE.search(raw)
    tag_m        = _TAG_RE.search(raw)
    importance_m = _IMPORTANCE_RE.search(raw)
    topics_m     = _TOPICS_RE.search(raw)

    criteria_met = (
        [int(n.strip()) for n in criteria_m.group(1).split(",") if n.strip().isdigit()]
        if criteria_m else []
    )
    # Hard-enforce 3-criteria minimum regardless of Claude's "כן"
    approved = (
        bool(decision_m and decision_m.group(1) == "כן")
        and len(criteria_met) >= 3
    )
    reason     = reason_m.group(1).strip()     if reason_m     else ""
    tag        = tag_m.group(1).strip()        if tag_m        else "גלובלי"
    importance = int(importance_m.group(1))    if importance_m else 5
    topics     = (
        [t.strip() for t in topics_m.group(1).split(",") if t.strip()]
        if topics_m else []
    )

    return ClassificationResult(
        article=article,
        approved=approved,
        criteria_met=criteria_met,
        reason=reason,
        tag=tag,
        importance=min(max(importance, 1), 10),
        topics=topics,
    )


# ── Topic deduplication ────────────────────────────────────────────────────

_TOPIC_CHECK_SYSTEM = """אתה בודק כפילויות בסיקור עיתונאי.
ענה "כן" אם הכתבה החדשה מוסיפה מידע חדש ומשמעותי שלא כוסה ב-72 שעות האחרונות.
ענה "לא" אם מדובר בחזרה על אותו נושא ללא התפתחות מהותית.
ענה רק "כן" או "לא", ללא הסבר."""


async def topic_dedup_filter(
    approved: list[ClassificationResult],
    recent_sent: list[dict],
) -> list[ClassificationResult]:
    """Remove articles whose topics were already covered in the last 72 hours,
    unless Claude determines they add significant new information."""
    if not recent_sent or not approved:
        return approved

    # Collect all topics sent recently (only entries that have topics)
    recent_topics: set[str] = set(
        t for m in recent_sent for t in m.get("topics", [])
    )
    if not recent_topics:
        return approved  # Old log entries with no topics — skip dedup

    recent_context = "\n".join(
        f"- {m['title']} | נושאים: {', '.join(m.get('topics', ['—']))}"
        for m in recent_sent
    )

    client    = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CLAUDE)

    async def _check_one(r: ClassificationResult) -> ClassificationResult | None:
        # Fast path: no topic overlap → pass through without API call
        if not set(r.topics).intersection(recent_topics):
            return r

        # Overlap detected → ask Claude if this adds new info
        async with semaphore:
            try:
                resp = await client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=16,
                    system=_TOPIC_CHECK_SYSTEM,
                    messages=[{"role": "user", "content":
                        f"כתבה חדשה: {r.article.title}\n"
                        f"נושאים: {', '.join(r.topics)}\n\n"
                        f"כתבות שנשלחו ב-72 שעות האחרונות:\n{recent_context}\n\n"
                        "האם הכתבה החדשה מוסיפה מידע חדש ומשמעותי?"
                    }],
                )
                answer = resp.content[0].text.strip()
            except Exception as exc:
                print(f"  [topic-dedup] ⚠ Check error for '{r.article.title[:40]}': {exc}")
                return r  # On error, keep the article

        if answer.startswith("לא"):
            print(f"  [topic-dedup] ⏭ Skipping '{r.article.title[:55]}' — topic already covered")
            return None
        return r

    tasks   = [_check_one(r) for r in approved]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for item in results:
        if isinstance(item, Exception):
            print(f"  [topic-dedup] ⚠ Unexpected error: {item}")
        elif item is not None:
            out.append(item)
    return out
