"""Async article classifier using Claude API — batch mode with Haiku for cost efficiency."""
from __future__ import annotations

import asyncio
import json as _json
import re
from dataclasses import dataclass, field

import anthropic

import config
import stats
from feeds import Article


class CreditBalanceError(RuntimeError):
    """Raised when the Anthropic account has insufficient credits."""


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


# ── Shared context paragraph ───────────────────────────────────────────────

_CONTEXT = """אתה עוזר ליוצר תוכן ישראלי שמנהל ערוץ יוטיוב ופודקאסט על שווקים פיננסיים, מגמות כלכליות וטכנולוגיה. הקהל שלו הוא ישראלים שמתעניינים בשווקים, השקעות ומגמות גלובליות — לא סוחרים מקצועיים אלא אנשים חכמים שרוצים להבין מה קורה בעולם ואיך זה משפיע עליהם.

ההודעות שאתה מנסח נשלחות בוואטסאפ לקהל שלו. המטרה היא לספק עדכון קצר, חכם ומעניין שגורם לאנשים להרגיש שהם מבינים מה קורה — לא להפחיד, לא למכור, לא ליצור FOMO. הטון הוא של חבר חכם שמסביר לך מה קורה בעולם."""


# ── Batch classification system prompt ────────────────────────────────────

_BATCH_SYSTEM = _CONTEXT + "\n\n" + """אתה מסנן כתבות כלכליות-פיננסיות לניוזלטר השקעות.

כתבה עוברת אם היא עונה על לפחות 3 מתוך 15 הקריטריונים:
1. השפעה מוחשית על המציאות
2. גיבוי בנתוני מאקרו
3. שיבוש תעשיות מסורתיות
4. טריגר רגולטורי מובהק
5. השפעה רוחבית
6. תמורות בשרשראות אספקה
7. שינוי בהתנהגות צרכנים
8. השקעות עתק בתשתיות
9. מיפוי מרוויחים ומפסידים
10. פתרון צווארי בקבוק גלובליים
11. אימוץ מוסדי נרחב
12. ניסוח נטול יח"צ
13. מבנה יסודי מול טרנד חולף
14. מעקב אחר זרימת ההון
15. פוטנציאל סיפורי ברור

כתבה נדחית אם: ידיעה כללית ללא השפעה, דעה שטחית, הייפ/יח"צ, ספורט/פוליטיקה ללא קשר כלכלי, רכילות.

ענה ב-JSON בלבד (ללא טקסט נוסף לפני או אחרי):
{"results":[{"id":1,"approved":true,"criteria":[1,5,14],"reason":"משפט קצר","tag":"ארה\\"ב","importance":7,"topics":["פד","ריבית"]},{"id":2,"approved":false,"criteria":[],"reason":"ידיעה שטחית","tag":"גלובלי","importance":2,"topics":[]}]}

כללים:
- tag חייב להיות בדיוק אחד מ: ארה"ב / ישראל / גלובלי
- importance: מספר שלם 1-10
- approved חייב להיות false אם criteria מכיל פחות מ-2 פריטים
- reason: משפט אחד קצר בעברית
- topics: עד 4 תגיות נושא בעברית"""


# ── Public entry points ────────────────────────────────────────────────────

async def classify_all(articles: list[Article]) -> list[ClassificationResult]:
    """Classify articles in batches using Haiku — drastically fewer API calls."""
    if not articles:
        return []

    client     = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    batch_size = config.CLASSIFIER_BATCH_SIZE
    batches    = [articles[i:i + batch_size] for i in range(0, len(articles), batch_size)]

    print(f"  Batches: {len(batches)} × ≤{batch_size} articles → {config.CLAUDE_CLASSIFIER_MODEL}")

    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CLAUDE)

    async def _run_batch(batch: list[Article]) -> list[ClassificationResult]:
        async with semaphore:
            return await _classify_batch(client, batch)

    batch_results = await asyncio.gather(*[_run_batch(b) for b in batches], return_exceptions=True)

    out: list[ClassificationResult] = []
    for res in batch_results:
        if isinstance(res, CreditBalanceError):
            raise res
        if isinstance(res, Exception):
            print(f"  [classifier] ⚠ Batch error: {res}")
        else:
            out.extend(res)
    return out


# ── Batch API call ─────────────────────────────────────────────────────────

async def _classify_batch(
    client:      anthropic.AsyncAnthropic,
    articles:    list[Article],
    attempt:     int = 1,
    max_retries: int = 3,
) -> list[ClassificationResult]:
    articles_text = "\n\n".join(
        f"[{i+1}] כותרת: {a.title}\nמקור: {a.source}\nתקציר: {a.summary[:300]}"
        for i, a in enumerate(articles)
    )

    try:
        response = await client.messages.create(
            model=config.CLAUDE_CLASSIFIER_MODEL,
            max_tokens=min(200 * len(articles), 4096),
            system=_BATCH_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"סנן את {len(articles)} הכתבות הבאות:\n\n{articles_text}",
            }],
        )
        stats.record(
            response.usage.input_tokens,
            response.usage.output_tokens,
            model=config.CLAUDE_CLASSIFIER_MODEL,
        )
        return _parse_batch(response.content[0].text, articles)

    except anthropic.RateLimitError:
        if attempt < max_retries:
            wait = (2 ** (attempt - 1)) * 5
            print(f"  [classifier] Rate limited — retrying batch in {wait}s…")
            await asyncio.sleep(wait)
            return await _classify_batch(client, articles, attempt + 1, max_retries)
        raise

    except anthropic.APIStatusError as exc:
        if exc.status_code == 400 and "credit balance is too low" in str(exc).lower():
            raise CreditBalanceError(
                f"Anthropic credit balance is too low — נא לטעון קרדיטים בחשבון. ({exc})"
            ) from exc
        if exc.status_code >= 500 and attempt < max_retries:
            wait = (2 ** (attempt - 1)) * 3
            await asyncio.sleep(wait)
            return await _classify_batch(client, articles, attempt + 1, max_retries)
        raise


# ── Batch response parser ──────────────────────────────────────────────────

def _parse_batch(raw: str, articles: list[Article]) -> list[ClassificationResult]:
    # Extract JSON object (Claude sometimes adds a preamble)
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        print(f"  [classifier] ⚠ No JSON found in batch response — rejecting {len(articles)} articles")
        return _reject_all(articles)

    try:
        data        = _json.loads(json_match.group())
        results_map = {int(r["id"]): r for r in data.get("results", [])}
    except (_json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"  [classifier] ⚠ Batch JSON parse error ({exc}) — rejecting {len(articles)} articles")
        return _reject_all(articles)

    out: list[ClassificationResult] = []
    for i, article in enumerate(articles):
        r        = results_map.get(i + 1, {})
        criteria = [int(c) for c in r.get("criteria", []) if str(c).isdigit()]
        approved = bool(r.get("approved", False)) and len(criteria) >= 2
        tag_raw  = r.get("tag", "גלובלי")
        tag      = tag_raw if tag_raw in ('ארה"ב', "ישראל", "גלובלי") else "גלובלי"
        try:
            importance = min(max(int(r.get("importance", 5)), 1), 10)
        except (TypeError, ValueError):
            importance = 5
        topics = [t.strip() for t in r.get("topics", []) if isinstance(t, str) and t.strip()]

        out.append(ClassificationResult(
            article=article,
            approved=approved,
            criteria_met=criteria,
            reason=str(r.get("reason", "")).strip(),
            tag=tag,
            importance=importance,
            topics=topics[:4],
        ))
    return out


def _reject_all(articles: list[Article]) -> list[ClassificationResult]:
    return [
        ClassificationResult(
            article=a, approved=False, criteria_met=[],
            reason="batch parse error", tag="גלובלי", importance=1,
        )
        for a in articles
    ]


# ── Broad topic categories ─────────────────────────────────────────────────

# Maps a canonical category name to keywords that identify it.
# Matching is case-insensitive and substring-based.
_BROAD_CATEGORIES: dict[str, list[str]] = {
    "תשואות_אגח": [
        'אג"ח', "אגח", "תשואות", "תשואה", "bond", "bonds", "yield", "yields",
        "treasuries", "treasury", "ממשלתי", "ממשלתיות", "שוק האג",
    ],
    "נפט_אנרגיה": [
        "נפט", "איראן", 'אופ"ק', "opec", "oil", "crude", "energy", "אנרגיה",
        "גז טבעי", "natural gas",
    ],
    "ai_שבבים": [
        "ai", "בינה מלאכותית", "שבבים", "nvidia", "נבידיה", "nvda", "chips",
        "semiconductor", "מוליכים למחצה", "openai", "anthropic", "llm", "גנרטיבי",
    ],
    "ריבית_פד": [
        "פד", "ריבית", "פדרל ריזרב", "fed", "federal reserve", "fomc",
        "interest rate", "ריביות", "בנק מרכזי",
    ],
    "דולר_מטבעות": [
        "דולר", "מטבע", "שקל", "יורו", "dollar", "currency", "forex", "ין",
    ],
    "מניות_שוק": [
        "s&p", "spx", "נאסדק", "nasdaq", "דאו", "dow", "מניות", "בורסה",
        "wall street", "שוק מניות", "equity", "equities",
    ],
    "סין_סחר": [
        "סין", "סחר", "מכסים", "china", "trade", "tariffs", "customs", "יבוא",
        "יצוא", "export", "import",
    ],
    "אינפלציה_מאקרו": [
        "אינפלציה", "cpi", "pce", "מדד מחירים", "inflation", "deflation",
        "מאקרו", "gdp", "תמ\"ג",
    ],
    "קריפטו": [
        "קריפטו", "ביטקוין", "אתריום", "crypto", "bitcoin", "ethereum",
        "blockchain", "בלוקצ'יין",
    ],
    "נדלן": [
        "נדל\"ן", "נדלן", "דיור", "משכנתא", "real estate", "housing", "mortgage",
        "שכר דירה",
    ],
    "ישראל_כלכלה": [
        "ישראל", "ממשלת ישראל", "בנק ישראל", "כלכלת ישראל", "שוק ישראלי",
        "מלחמה", "ביטחון",
    ],
}


def _topics_to_broad_categories(topics: list[str]) -> set[str]:
    """Map article topic tags to broad canonical category names."""
    cats: set[str] = set()
    topics_lower = [t.lower() for t in topics]
    for cat, keywords in _BROAD_CATEGORIES.items():
        for kw in keywords:
            if any(kw.lower() in t for t in topics_lower):
                cats.add(cat)
                break
    return cats


# ── Topic deduplication ────────────────────────────────────────────────────

_TOPIC_CHECK_SYSTEM = _CONTEXT + "\n\n" + """אתה בודק כפילויות בסיקור עיתונאי.

חוק ברזל: אם הנושא כבר כוסה ב-48 שעות האחרונות — סנן החוצה, אלא אם יש אירוע חדש ספציפי.

"אירוע חדש ספציפי" = נתון חדש שפורסם, החלטה שהתקבלה, שינוי כיוון מפתיע, הכרזה רשמית.
"לא אירוע חדש" = ניתוח נוסף של אותו מצב, פרשנות, עדכון שוטף, "תשואות עלו שוב".

ענה "כן" רק אם יש אירוע חדש ספציפי שלא הופיע בכתבות הקודמות.
ענה "לא" בכל מקרה אחר — כולל כשהכותרת שונה אך הנושא זהה.
ענה רק "כן" או "לא", ללא הסבר."""


async def topic_dedup_filter(
    approved: list[ClassificationResult],
    recent_sent: list[dict],
) -> list[ClassificationResult]:
    """Remove articles whose broad topics were already covered in the last 48 hours,
    unless Claude identifies a specific new event (not just new analysis)."""
    if not recent_sent or not approved:
        return approved

    # Build broad category coverage from recently sent articles
    recent_broad_cats: set[str] = set()
    for m in recent_sent:
        recent_broad_cats.update(_topics_to_broad_categories(m.get("topics", [])))

    # Fallback: exact topic matching for articles outside known categories
    recent_exact_topics: set[str] = set(
        t for m in recent_sent for t in m.get("topics", [])
    )

    if not recent_broad_cats and not recent_exact_topics:
        return approved

    recent_context = "\n".join(
        f"- {m['title']} | נושאים: {', '.join(m.get('topics', ['—']))}"
        for m in recent_sent
    )

    client    = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CLAUDE)

    async def _check_one(r: ClassificationResult) -> ClassificationResult | None:
        article_broad_cats = _topics_to_broad_categories(r.topics)
        broad_overlap      = article_broad_cats & recent_broad_cats
        exact_overlap      = set(r.topics) & recent_exact_topics

        # Pass through if no overlap in either broad categories or exact topics
        if not broad_overlap and not exact_overlap:
            return r

        overlap_desc = (
            f"קטגוריות: {broad_overlap}" if broad_overlap
            else f"נושאים: {exact_overlap}"
        )
        print(f"  [topic-dedup] 🔍 Checking '{r.article.title[:55]}' — {overlap_desc}")

        async with semaphore:
            try:
                resp = await client.messages.create(
                    model=config.CLAUDE_CLASSIFIER_MODEL,
                    max_tokens=16,
                    system=_TOPIC_CHECK_SYSTEM,
                    messages=[{"role": "user", "content":
                        f"כתבה חדשה: {r.article.title}\n"
                        f"נושאים: {', '.join(r.topics)}\n\n"
                        f"כתבות שנשלחו ב-48 שעות האחרונות:\n{recent_context}\n\n"
                        "האם הכתבה החדשה מביאה אירוע חדש ספציפי (לא רק ניתוח נוסף של אותו מצב)?"
                    }],
                )
                stats.record(
                    resp.usage.input_tokens,
                    resp.usage.output_tokens,
                    model=config.CLAUDE_CLASSIFIER_MODEL,
                )
                answer = resp.content[0].text.strip()
            except anthropic.APIStatusError as exc:
                if exc.status_code == 400 and "credit balance is too low" in str(exc).lower():
                    raise CreditBalanceError(
                        f"Anthropic credit balance is too low — נא לטעון קרדיטים בחשבון. ({exc})"
                    ) from exc
                print(f"  [topic-dedup] ⚠ Check error for '{r.article.title[:40]}': {exc}")
                return r
            except Exception as exc:
                print(f"  [topic-dedup] ⚠ Check error for '{r.article.title[:40]}': {exc}")
                return r

        if answer.startswith("לא"):
            print(f"  [topic-dedup] ⏭ Skipping '{r.article.title[:55]}' — no new event")
            return None
        return r

    tasks   = [_check_one(r) for r in approved]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[ClassificationResult] = []
    for item in results:
        if isinstance(item, CreditBalanceError):
            raise item
        if isinstance(item, Exception):
            print(f"  [topic-dedup] ⚠ Unexpected error: {item}")
        elif item is not None:
            out.append(item)
    return out


def within_batch_dedup(approved: list[ClassificationResult]) -> list[ClassificationResult]:
    """Remove same-topic duplicates within a single batch using broad categories.

    Assumes `approved` is already sorted by importance (desc).
    Keeps the first (highest-importance) article per broad category.
    Falls back to exact topic matching for topics outside known categories.
    """
    seen_broad_cats: set[str] = set()
    seen_exact_topics: set[str] = set()
    out: list[ClassificationResult] = []
    for r in approved:
        if not r.topics:
            out.append(r)
            continue
        article_broad_cats = _topics_to_broad_categories(r.topics)
        if article_broad_cats:
            overlap = article_broad_cats & seen_broad_cats
            if overlap:
                print(f"  [batch-dedup] ⏭ Skipping '{r.article.title[:55]}' — categories {overlap} already in batch")
                continue
            seen_broad_cats.update(article_broad_cats)
        else:
            overlap = set(r.topics) & seen_exact_topics
            if overlap:
                print(f"  [batch-dedup] ⏭ Skipping '{r.article.title[:55]}' — topics {overlap} already in batch")
                continue
        seen_exact_topics.update(r.topics)
        out.append(r)
    return out
