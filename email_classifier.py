"""World-news classifier for the morning email digest — separate pipeline.

This is intentionally a standalone module, not an extension of classifier.py:
it uses a different system prompt (global/geopolitical significance instead
of the 15 market-relevance criteria), a different result shape, and is only
ever called from main.py's `--collect-email-pool` mode. Nothing in the
WhatsApp send path imports this module.
"""
from __future__ import annotations

import asyncio
import json as _json
import re
from dataclasses import dataclass, field

import anthropic

import config
import stats
from feeds import Article


# ── Result model ─────────────────────────────────────────────────────────

@dataclass
class WorldClassificationResult:
    article:     Article
    approved:    bool
    reason:      str
    importance:  int              # 1-10
    topics:      list[str] = field(default_factory=list)


# ── Shared context ──────────────────────────────────────────────────────

_CONTEXT = """אתה עוזר בעריכת בריף בוקר יומי בעברית לקהל ישראלי שמתעניין בעולם, בכלכלה ובטכנולוגיה. הבריף נשלח במייל כל בוקר ומטרתו לתת תמונת מצב עולמית מהירה ואמינה — לא רק חדשות שוק."""


# ── Batch classification system prompt ────────────────────────────────────

_BATCH_SYSTEM = _CONTEXT + "\n\n" + """אתה מסנן כותרות חדשות עולם לבריף בוקר יומי.

כתבה עוברת אם היא עונה על משמעות גלובלית/גיאופוליטית משמעותית — למשל:
- אירוע ביטחוני/מלחמתי משמעותי (תקיפות, נפגעים, הסלמה, הפוגה)
- החלטה מדינית/דיפלומטית בעלת השפעה רחבה (הסכם, ביקור מדינה, סנקציות)
- אסון טבע, תאונת המונים, או אירוע בטיחות גדול
- התפתחות פוליטית מהותית במדינה משמעותית (בחירות, מהפך, משבר ממשלתי)
- אירוע בעל השלכה ישירה על ישראל או יהודים בעולם

כתבה נדחית אם: ידיעה מקומית שולית, ספורט, בידור/רכילות, דעה/טור ללא ידיעה בבסיסו, כותרת קליקבייט ללא תוכן עובדתי, כתבה ישנה/מחזור של סיפור מוכר בלי התפתחות חדשה.

ענה ב-JSON בלבד (ללא טקסט נוסף לפני או אחרי):
{"results":[{"id":1,"approved":true,"importance":8,"reason":"משפט קצר","topics":["אוקראינה","רוסיה"]},{"id":2,"approved":false,"importance":2,"reason":"ידיעה שולית","topics":[]}]}

כללים:
- importance: מספר שלם 1-10 (10 = אירוע היסטורי/משבר עולמי, 5 = ידיעה בינונית שכדאי לדעת, 1 = לא מעניין)
- reason: משפט אחד קצר בעברית
- topics: עד 3 תגיות נושא בעברית"""


# ── Public entry point ──────────────────────────────────────────────────

async def classify_all(articles: list[Article]) -> list[WorldClassificationResult]:
    """Classify world-news articles in batches using Haiku."""
    if not articles:
        return []

    client     = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    batch_size = config.CLASSIFIER_BATCH_SIZE
    batches    = [articles[i:i + batch_size] for i in range(0, len(articles), batch_size)]

    print(f"  [email_classifier] Batches: {len(batches)} × ≤{batch_size} articles → {config.CLAUDE_CLASSIFIER_MODEL}")

    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CLAUDE)

    async def _run_batch(batch: list[Article]) -> list[WorldClassificationResult]:
        async with semaphore:
            return await _classify_batch(client, batch)

    batch_results = await asyncio.gather(*[_run_batch(b) for b in batches], return_exceptions=True)

    out: list[WorldClassificationResult] = []
    for res in batch_results:
        if isinstance(res, Exception):
            print(f"  [email_classifier] ⚠ Batch error: {res}")
        else:
            out.extend(res)
    return out


async def _classify_batch(
    client:      anthropic.AsyncAnthropic,
    articles:    list[Article],
    attempt:     int = 1,
    max_retries: int = 3,
) -> list[WorldClassificationResult]:
    articles_text = "\n\n".join(
        f"[{i+1}] כותרת: {a.title}\nמקור: {a.source}\nתקציר: {a.summary[:300]}"
        for i, a in enumerate(articles)
    )

    try:
        response = await client.messages.create(
            model=config.CLAUDE_CLASSIFIER_MODEL,
            max_tokens=min(180 * len(articles), 4096),
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
            print(f"  [email_classifier] Rate limited — retrying batch in {wait}s…")
            await asyncio.sleep(wait)
            return await _classify_batch(client, articles, attempt + 1, max_retries)
        raise

    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500 and attempt < max_retries:
            wait = (2 ** (attempt - 1)) * 3
            await asyncio.sleep(wait)
            return await _classify_batch(client, articles, attempt + 1, max_retries)
        raise


def _parse_batch(raw: str, articles: list[Article]) -> list[WorldClassificationResult]:
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        print(f"  [email_classifier] ⚠ No JSON found in batch response — rejecting {len(articles)} articles")
        return _reject_all(articles)

    try:
        data        = _json.loads(json_match.group())
        results_map = {int(r["id"]): r for r in data.get("results", [])}
    except (_json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"  [email_classifier] ⚠ Batch JSON parse error ({exc}) — rejecting {len(articles)} articles")
        return _reject_all(articles)

    out: list[WorldClassificationResult] = []
    for i, article in enumerate(articles):
        r = results_map.get(i + 1, {})
        try:
            importance = min(max(int(r.get("importance", 3)), 1), 10)
        except (TypeError, ValueError):
            importance = 3
        approved = bool(r.get("approved", False))
        topics   = [t.strip() for t in r.get("topics", []) if isinstance(t, str) and t.strip()]

        out.append(WorldClassificationResult(
            article=article,
            approved=approved,
            reason=str(r.get("reason", "")).strip(),
            importance=importance,
            topics=topics[:3],
        ))
    return out


def _reject_all(articles: list[Article]) -> list[WorldClassificationResult]:
    return [
        WorldClassificationResult(article=a, approved=False, reason="batch parse error", importance=1)
        for a in articles
    ]
