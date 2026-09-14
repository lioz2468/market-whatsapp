#!/usr/bin/env python3
"""
Market WhatsApp Bot - RSS | Claude filter | WhatsApp

Usage:
  python main.py                          # preview + manual confirm
  python main.py --auto                   # send without asking
  python main.py --dry-run                # preview only, no send
  python main.py --morning-digest         # send a digest of recent articles
  python main.py --provider green         # use Green API instead of Twilio
  python main.py --skip-humanizer         # skip style rewriting
  python main.py --ab                     # show before/after humanizer
  python main.py --test "your message"    # send text directly, skip all feeds
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import colorama
from colorama import Fore, Style

import config
import feeds
import classifier
import composer
import humanizer
import stats

colorama.init(autoreset=True)


# ── Sent log ───────────────────────────────────────────────────────────────

class SentLog:
    def __init__(self):
        self._data = self._load()

    def _load(self) -> dict:
        if config.SENT_LOG_PATH.exists():
            try:
                return json.loads(config.SENT_LOG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"hashes": {}, "messages": [], "last_auto_run": None}

    def is_sent(self, hash_: str) -> bool:
        return hash_ in self._data["hashes"]

    def mark_sent(self, results: list[classifier.ClassificationResult]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for r in results:
            self._data["hashes"][r.article.hash] = now
            self._data["messages"].append({
                "sent_at":    now,
                "title":      r.article.title,
                "source":     r.article.source,
                "url":        r.article.url,   # additive field — used by the email digest, ignored elsewhere
                "message":    r.final_message,
                "importance": r.importance,
                "tag":        r.tag,
                "topics":     r.topics,
            })
        config.SENT_LOG_PATH.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def last_auto_run_at(self) -> datetime | None:
        """Timestamp of the last *scheduled* (non-manual) run, regardless of
        whether it ended up sending a message or bailing out early because
        nothing qualified. Used to space out automatic runs without manual
        workflow_dispatch runs interfering with that cadence."""
        ts = self._data.get("last_auto_run")
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    def mark_auto_run(self) -> None:
        self._data["last_auto_run"] = datetime.now(timezone.utc).isoformat()
        config.SENT_LOG_PATH.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def recent_messages(self, hours: int) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        out = []
        for m in self._data["messages"]:
            try:
                sent_at = datetime.fromisoformat(m["sent_at"])
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                if sent_at >= cutoff:
                    out.append(m)
            except (ValueError, KeyError):
                pass
        return out


# ── Pending queue ──────────────────────────────────────────────────────────

class PendingQueue:
    """Articles approved but not yet sent — drained one per run."""

    def __init__(self):
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if config.PENDING_PATH.exists():
            try:
                return json.loads(config.PENDING_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self) -> None:
        config.PENDING_PATH.write_text(
            json.dumps(self._items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def __len__(self) -> int:
        return len(self._items)

    def peek(self) -> dict | None:
        return self._items[0] if self._items else None

    def hashes(self) -> set[str]:
        return {item["hash"] for item in self._items}

    def pop(self) -> dict:
        """Remove and return the first pending item, then persist."""
        item = self._items.pop(0)
        self._save()
        return item

    def push(self, results: list[classifier.ClassificationResult]) -> None:
        """Append results to the queue and persist."""
        for r in results:
            self._items.append({
                "final_message": r.final_message,
                "title":         r.article.title,
                "source":        r.article.source,
                "hash":          r.article.hash,
                "importance":    r.importance,
                "tag":           r.tag,
                "topics":        r.topics,
            })
        self._save()


def _pending_to_result(item: dict) -> classifier.ClassificationResult:
    """Reconstruct a minimal ClassificationResult from a stored pending item."""
    article = feeds.Article(
        title=item["title"], url="", summary="", published="",
        source=item["source"], lang="", hash=item["hash"],
    )
    r = classifier.ClassificationResult(
        article=article, approved=True, criteria_met=[],
        reason="", tag=item["tag"], importance=item["importance"],
        topics=item.get("topics", []),
    )
    r.message = item["final_message"]
    return r


# ── Shabbat gate ───────────────────────────────────────────────────────────

_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def _is_shabbat() -> bool:
    """True from Friday 17:00 until Sunday 09:00 (Israel time)."""
    now = datetime.now(_ISRAEL_TZ)
    wd  = now.weekday()   # Friday=4, Saturday=5, Sunday=6
    return (
        (wd == 4 and now.hour >= 17)  # Friday from 17:00
        or wd == 5                     # all of Saturday
        or (wd == 6 and now.hour < 9)  # Sunday before 09:00
    )


# Active send window — must match the .github/workflows/market-news.yml cron
# comment (08:00-21:30 Israel time). This is the actual enforcement point:
# the cron's hour range only controls GitHub's *internal* schedule trigger,
# but automated runs can also arrive via repository_dispatch from an external
# backup scheduler (cron-job.org) that isn't bound by that cron config at all
# — if it's set to fire 24/7, this is what stops a 3am WhatsApp message.
_ACTIVE_START_MIN = 8 * 60          # 08:00
_ACTIVE_END_MIN   = 21 * 60 + 30    # 21:30


def _is_outside_active_hours() -> bool:
    now = datetime.now(_ISRAEL_TZ)
    minutes = now.hour * 60 + now.minute
    return not (_ACTIVE_START_MIN <= minutes <= _ACTIVE_END_MIN)


# ── Safety filter ──────────────────────────────────────────────────────────

_BLOCKED_PHRASES = [
    "אי אפשר לנסח",
    "כדאי לוודא",
    "האם מדובר",
    "אם תוכל",
    "לא ניתן לאמת",
    "לא ניתן לנסח",
    "מקור יחיד",
    "שגיאה",
    "error",
    "עדכון:",
]

_BLOCKED_PREFIXES = ("רגע", "שניה", "בעיה")

_MIN_WORDS = 30
_MAX_WORDS = 200


def _safety_filter(msg: str) -> tuple[bool, str]:
    """
    Last-gate check before any WhatsApp send.
    Strips one leading 'עדכון: ' (added by this bot) before checking,
    so the bot-controlled prefix never triggers the 'עדכון:' phrase block.
    Returns (is_blocked, reason).
    """
    check = msg[len("עדכון: "):] if msg.startswith("עדכון: ") else msg
    check_lower = check.lower()

    for phrase in _BLOCKED_PHRASES:
        if phrase.lower() in check_lower:
            return True, f"contains blocked phrase: {phrase!r}"

    if "?" in check:
        return True, "contains question mark"

    words = check.split()
    first_word = words[0].rstrip(",.!?:") if words else ""
    if first_word in _BLOCKED_PREFIXES:
        return True, f"starts with blocked word: {first_word!r}"

    wc = len(words)
    if wc < _MIN_WORDS:
        return True, f"too short ({wc} words, min {_MIN_WORDS})"
    if wc > _MAX_WORDS:
        return True, f"too long ({wc} words, max {_MAX_WORDS})"

    return False, ""


# ── Sending ────────────────────────────────────────────────────────────────

async def _send(messages: list[str], provider: str, skip_filter: bool = False) -> None:
    if not skip_filter and _is_shabbat():
        print(f"  {Fore.YELLOW}⛔ שבת — שליחה מושהית עד ראשון (שעון ישראל).{Style.RESET_ALL}")
        return

    safe: list[str] = []
    for msg in messages:
        if skip_filter:
            safe.append(msg)
        else:
            blocked, reason = _safety_filter(msg)
            if blocked:
                print(f"  {Fore.RED}BLOCKED: message failed safety filter ({reason}){Style.RESET_ALL}")
                continue
            safe.append(msg)

    if not safe:
        return

    if provider == "twilio":
        import whatsapp_twilio as wa
        sids = await wa.send_all(safe)
        for sid in sids:
            print(f"  {Fore.GREEN}✓ Sent via Twilio — SID: {sid}{Style.RESET_ALL}")
    elif provider == "green":
        import whatsapp_green as wa
        responses = await wa.send_all(safe)
        for resp in responses:
            mid = resp.get("idMessage", "?")
            print(f"  {Fore.GREEN}✓ Sent via Green API — id: {mid}{Style.RESET_ALL}")
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ── Preview / display ──────────────────────────────────────────────────────

def _print_divider(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _preview_results(
    results: list[classifier.ClassificationResult],
    show_ab: bool = False,
) -> None:
    if not results:
        print(f"\n  {Fore.YELLOW}No articles passed the filter.{Style.RESET_ALL}")
        return

    print(f"\n{'='*60}")
    print(f"{Fore.CYAN}{Style.BRIGHT}  📰 {len(results)} article(s) passed the filter{Style.RESET_ALL}")
    print(f"{'='*60}")

    for i, r in enumerate(results, 1):
        imp_color = Fore.RED if r.importance >= 8 else (Fore.YELLOW if r.importance >= 6 else Fore.WHITE)

        print(f"\n{Fore.CYAN}[{i}/{len(results)}]{Style.RESET_ALL} {r.article.source} | "
              f"{r.tag} | {imp_color}⭐ {r.importance}/10{Style.RESET_ALL}")
        print(f"  {Style.BRIGHT}{r.article.title}{Style.RESET_ALL}")
        print(f"  Criteria: {r.criteria_met} | {r.reason}")
        _print_divider()

        if show_ab and r.humanized_msg and r.humanized_msg != r.message:
            print(f"  {Fore.YELLOW}BEFORE (Claude){Style.RESET_ALL}")
            print(f"  {r.message}")
            print(f"  {Fore.GREEN}AFTER (humanized){Style.RESET_ALL}")
            print(f"  {r.humanized_msg}")
        else:
            print(f"  {Fore.GREEN}{r.final_message}{Style.RESET_ALL}")


def _print_cost() -> None:
    t = stats.totals()
    if t["calls"] == 0:
        return
    print(f"\n  {Fore.YELLOW}{stats.summary()}{Style.RESET_ALL}")


def _confirm() -> bool:
    answer = input(f"\n  {Style.BRIGHT}שלח? (y/n): {Style.RESET_ALL}").strip().lower()
    return answer in {"y", "yes", "כן", "י"}


# ── Main pipeline ──────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    config.validate_claude()
    if not args.dry_run:
        config.validate_provider(args.provider)

    stats.reset()
    sent_log = SentLog()
    pending  = PendingQueue()

    # ── 0. Minimum-gap guard (scheduled runs only) ─────────────────────────
    # Manual runs (workflow_dispatch, or running locally) always bypass this
    # gate and never affect it — the 85-min spacing is only enforced between
    # consecutive *scheduled* runs, whatever their outcome (sent or bailed
    # out early because nothing qualified). This keeps a manual test/run
    # from either getting blocked, or throwing off the next scheduled run's
    # timing.
    #
    # repository_dispatch is treated the same as schedule: it's how the
    # external cron-job.org backup pings this workflow to cover firings
    # GitHub's own `schedule` trigger silently drops. It must be gated
    # identically, or the backup would bypass the 85-min spacing and spam
    # WhatsApp every time it fires. workflow_dispatch stays ungated because
    # it's only ever fired by a human from the Actions tab.
    is_scheduled = os.getenv("GITHUB_EVENT_NAME") in ("schedule", "repository_dispatch")
    if is_scheduled and _is_outside_active_hours():
        print(
            f"\n  {Fore.YELLOW}🌙 Outside active hours (08:00–21:30 IL) — "
            f"skipping automated trigger.{Style.RESET_ALL}"
        )
        return
    if is_scheduled:
        last_auto = sent_log.last_auto_run_at()
        if last_auto is not None:
            elapsed = datetime.now(timezone.utc) - last_auto
            min_gap = timedelta(minutes=config.MIN_SEND_INTERVAL_MINUTES)
            if elapsed < min_gap:
                remaining = min_gap - elapsed
                mins = int(remaining.total_seconds() // 60)
                print(
                    f"\n  {Fore.YELLOW}⏱ Last scheduled run {int(elapsed.total_seconds() // 60)} min ago — "
                    f"waiting for {config.MIN_SEND_INTERVAL_MINUTES}min gap ({mins} min left).{Style.RESET_ALL}"
                )
                return
        sent_log.mark_auto_run()

    # ── 1. Drain pending queue (one article per run) ─────────────────────
    if len(pending):
        item   = pending.peek()
        result = _pending_to_result(item)
        print(f"\n{Fore.CYAN}📬 Pending queue: {len(pending)} article(s) waiting{Style.RESET_ALL}")
        print(f"  {Style.BRIGHT}{result.article.title}{Style.RESET_ALL}")
        print(f"  {result.article.source} | {result.tag} | ⭐ {result.importance}/10")
        _print_divider()
        print(f"  {Fore.GREEN}{result.final_message}{Style.RESET_ALL}")

        if args.dry_run:
            print(f"\n  {Fore.YELLOW}--dry-run: nothing sent.{Style.RESET_ALL}")
            return
        if not args.auto and not _confirm():
            print(f"\n  {Fore.YELLOW}Cancelled.{Style.RESET_ALL}")
            return

        print(f"\n{Fore.CYAN}📤 Sending via {args.provider}…{Style.RESET_ALL}")
        await _send([result.final_message], args.provider)
        pending.pop()
        sent_log.mark_sent([result])
        remaining = len(pending)
        if remaining:
            print(f"  {Fore.YELLOW}{remaining} article(s) still in pending queue.{Style.RESET_ALL}")
        print(f"\n  {Fore.GREEN}✓ Done — pending article sent, log updated.{Style.RESET_ALL}")
        return

    # ── 2. Fetch feeds ──────────────────────────────────────────────────
    print(f"\n{Fore.CYAN}📡 Fetching RSS feeds…{Style.RESET_ALL}")
    all_articles, _ = await feeds.fetch_all()

    # ── 2. Deduplicate ──────────────────────────────────────────────────
    new_articles = [a for a in all_articles if not sent_log.is_sent(a.hash)]
    print(f"  New (not yet sent): {len(new_articles)}")

    if not new_articles:
        print(f"\n  {Fore.YELLOW}Nothing new to process.{Style.RESET_ALL}")
        return

    # ── 3. Pre-filter (no API cost) ──────────────────────────────────────
    recent_sent_titles = [m["title"] for m in sent_log.recent_messages(18)]
    new_articles, pre_skipped = feeds.pre_filter(new_articles, sent_titles=recent_sent_titles)
    if pre_skipped:
        print(f"  Pre-filter: -{pre_skipped} irrelevant/stale | Remaining: {len(new_articles)}")
    if not new_articles:
        print(f"\n  {Fore.YELLOW}All articles filtered out by pre-filter.{Style.RESET_ALL}")
        return

    # Candidates considered this run, for the Twitter "unused" reservoir —
    # anything here not sent or pending by the time we're done gets saved
    # back so it can be re-offered instead of lost once since_id moves on.
    twitter_candidates = [a for a in new_articles if a.source.startswith("Twitter @")]

    try:
        # ── 4. Classify ─────────────────────────────────────────────────
        print(f"\n{Fore.CYAN}🧠 Classifying {len(new_articles)} article(s) with Claude…{Style.RESET_ALL}")
        results = await classifier.classify_all(new_articles)

        approved = sorted(
            (r for r in results if r.approved and r.importance >= config.MIN_IMPORTANCE_SCORE),
            key=lambda r: r.importance,
            reverse=True,
        )[:config.MAX_ARTICLES_PER_RUN]
        rejected = len(results) - len(approved)
        print(f"  Approved: {len(approved)} (cap {config.MAX_ARTICLES_PER_RUN}) | Rejected: {rejected}")

        if not approved:
            print(f"\n  {Fore.YELLOW}No articles met the threshold (score ≥ {config.MIN_IMPORTANCE_SCORE}).{Style.RESET_ALL}")
            _print_cost()
            return

        # ── 5. Topic deduplication (18h window) ─────────────────────────
        force_update_prefix = False
        recent_sent = sent_log.recent_messages(18)
        if recent_sent:
            print(f"\n{Fore.CYAN}🔍 Topic dedup — checking against {len(recent_sent)} article(s) from last 18h…{Style.RESET_ALL}")
            pre_dedup_approved = approved[:]
            before = len(approved)
            approved = await classifier.topic_dedup_filter(approved, recent_sent)
            skipped = before - len(approved)
            if skipped:
                print(f"  Skipped {skipped} duplicate topic(s)")
            if not approved:
                print(f"\n  {Fore.YELLOW}כל הכתבות הן כפילויות נושאים — שולח את הכי גבוהה כ'עדכון'.{Style.RESET_ALL}")
                approved = [pre_dedup_approved[0]]
                force_update_prefix = True

        # ── 5b. Within-batch dedup — prevent same topic queued multiple times ──
        before = len(approved)
        approved = classifier.within_batch_dedup(approved)
        skipped = before - len(approved)
        if skipped:
            print(f"  Batch dedup: -{skipped} same-topic duplicate(s)")

        # ── 6. Compose messages ───────────────────────────────────────────
        print(f"\n{Fore.CYAN}✍️  Composing {len(approved)} message(s)…{Style.RESET_ALL}")
        await composer.compose_all(approved)

        # ── 7. Humanizer (optional) ───────────────────────────────────────
        profile = None
        if not args.skip_humanizer:
            profile = humanizer.load_profile()
            if profile:
                print(f"\n{Fore.CYAN}🎨 Humanizing messages…{Style.RESET_ALL}")
                await humanizer.humanize_all(approved, profile=profile)
            else:
                print(f"  {Fore.YELLOW}[humanizer] No style_profile.json found — skipping.{Style.RESET_ALL}")

        # ── 8. Sort by importance ─────────────────────────────────────────
        approved.sort(key=lambda r: r.importance, reverse=True)

        # ── 9. Preview ─────────────────────────────────────────────────────
        # Mark which article will be sent now vs queued for later
        if len(approved) > 1:
            print(f"\n  {Fore.CYAN}[NOW]{Style.RESET_ALL} Sending top article. "
                  f"{Fore.YELLOW}{len(approved)-1} article(s) → pending queue.{Style.RESET_ALL}")
        _preview_results(approved, show_ab=args.ab)
        _print_cost()

        if args.dry_run:
            print(f"\n  {Fore.YELLOW}--dry-run: nothing sent.{Style.RESET_ALL}")
            return

        # ── 10. Send top article; queue the rest ─────────────────────────
        if not args.auto:
            if not _confirm():
                print(f"\n  {Fore.YELLOW}Cancelled.{Style.RESET_ALL}")
                return

        to_send        = None
        failed_compose = []

        for candidate in approved:
            if not candidate.final_message:
                print(
                    f"\n  {Fore.YELLOW}⚠ No message for \"{candidate.article.title[:60]}\" "
                    f"— retrying composition…{Style.RESET_ALL}"
                )
                await composer.compose_all([candidate])
            if candidate.final_message:
                to_send = candidate
                break
            print(f"  {Fore.RED}✗ Retry failed — skipping article.{Style.RESET_ALL}")
            failed_compose.append(candidate)

        if to_send is None:
            print(f"\n  {Fore.RED}All articles failed composition — nothing sent.{Style.RESET_ALL}")
            return

        to_queue = [
            r for r in approved
            if r is not to_send and r not in failed_compose and r.final_message
        ]

        print(f"\n{Fore.CYAN}📤 Sending via {args.provider}…{Style.RESET_ALL}")
        msg_to_send = ("עדכון: " + to_send.final_message) if force_update_prefix else to_send.final_message
        await _send([msg_to_send], args.provider)      # single message, always
        sent_log.mark_sent([to_send])

        if to_queue:
            pending.push(to_queue)
            print(f"  {Fore.YELLOW}{len(to_queue)} article(s) saved to pending queue.{Style.RESET_ALL}")

        print(f"\n  {Fore.GREEN}✓ Done — 1 message sent, log updated.{Style.RESET_ALL}")
    finally:
        pending_hashes = pending.hashes()
        still_unused = [
            a for a in twitter_candidates
            if not sent_log.is_sent(a.hash) and a.hash not in pending_hashes
        ]
        feeds.save_unused_twitter_articles(still_unused)


# ── Morning digest pipeline ────────────────────────────────────────────────

async def run_morning_digest(args: argparse.Namespace) -> None:
    config.validate_claude()
    if not args.dry_run:
        config.validate_provider(args.provider)

    sent_log = SentLog()
    recent   = sent_log.recent_messages(config.DIGEST_HOURS)

    if not recent:
        print(f"  {Fore.YELLOW}No messages in the last {config.DIGEST_HOURS}h for digest.{Style.RESET_ALL}")
        return

    print(f"\n{Fore.CYAN}☀️  Morning digest — {len(recent)} items from last {config.DIGEST_HOURS}h{Style.RESET_ALL}")

    # Build fake ClassificationResult list from log
    digest_results = []
    for m in sorted(recent, key=lambda x: x.get("importance", 5), reverse=True):
        # We only have the message stored; use it directly
        class _R:
            pass
        r = _R()
        r.final_message = m.get("message", "")
        r.importance    = m.get("importance", 5)
        r.tag           = m.get("tag", "—")
        r.article       = _R()
        r.article.title = m.get("title", "")
        r.article.source = m.get("source", "")
        r.article.summary = ""
        r.criteria_met  = []
        r.reason        = ""
        r.message       = r.final_message
        r.humanized_msg = ""
        digest_results.append(r)

    # Compose digest with Claude
    client = __import__("anthropic").AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    digest_text = await composer.compose_digest(digest_results)  # type: ignore[arg-type]

    print(f"\n{Fore.GREEN}{'─'*60}")
    print(digest_text)
    print(f"{'─'*60}{Style.RESET_ALL}")

    if args.dry_run:
        print(f"\n  {Fore.YELLOW}--dry-run: nothing sent.{Style.RESET_ALL}")
        return

    if not args.auto and not _confirm():
        print(f"\n  {Fore.YELLOW}Cancelled.{Style.RESET_ALL}")
        return

    await _send([digest_text], args.provider, skip_filter=True)
    print(f"\n  {Fore.GREEN}✓ Digest sent.{Style.RESET_ALL}")


# ── Email digest pool ──────────────────────────────────────────────────────
# Populates email_digest.json for the morning email. Fully separate from the
# WhatsApp send pipeline above: reads sent_log.json (read-only) and writes
# only email_digest.json. Never calls _send(), never touches sent_log.json,
# never sends WhatsApp or any other message. Safe to run on its own schedule.

async def run_collect_email_pool(args: argparse.Namespace) -> None:
    config.validate_claude()
    import email_classifier
    import email_tech_classifier

    print(f"\n{Fore.CYAN}📡 Fetching world-news feeds…{Style.RESET_ALL}")
    world_articles, _ = await feeds.fetch_feed_list(config.WORLD_RSS_FEEDS)

    world_articles, pre_skipped = feeds.pre_filter(
        world_articles, max_age_hours=config.EMAIL_LOOKBACK_HOURS
    )
    print(f"  After pre-filter: {len(world_articles)} (-{pre_skipped})")

    world_items: list[dict] = []
    if world_articles:
        print(f"\n{Fore.CYAN}🧠 Classifying {len(world_articles)} world article(s)…{Style.RESET_ALL}")
        results = await email_classifier.classify_all(world_articles)
        approved = sorted(
            (r for r in results if r.approved and r.importance >= config.MIN_WORLD_IMPORTANCE_SCORE),
            key=lambda r: r.importance,
            reverse=True,
        )[:config.MAX_WORLD_ARTICLES]
        print(f"  Approved: {len(approved)} (cap {config.MAX_WORLD_ARTICLES})")

        world_items = [
            {
                "title":      r.article.title,
                "source":     r.article.source,
                "url":        r.article.url,
                "summary":    r.article.summary[:400],
                "importance": r.importance,
                "topics":     r.topics,
                "published":  r.article.published,
            }
            for r in approved
        ]

    # ── Tech: dedicated feeds + classifier (see TECH_RSS_FEEDS) — almost
    # nothing tech-related clears the WhatsApp bot's 15-criteria filter, so
    # reusing sent_log.json (like business does below) left this near-empty.
    print(f"\n{Fore.CYAN}📡 Fetching tech-news feeds…{Style.RESET_ALL}")
    tech_articles, _ = await feeds.fetch_feed_list(config.TECH_RSS_FEEDS)

    tech_articles, tech_pre_skipped = feeds.pre_filter(
        tech_articles, max_age_hours=config.EMAIL_LOOKBACK_HOURS
    )
    print(f"  After pre-filter: {len(tech_articles)} (-{tech_pre_skipped})")

    tech_items: list[dict] = []
    if tech_articles:
        print(f"\n{Fore.CYAN}🧠 Classifying {len(tech_articles)} tech article(s)…{Style.RESET_ALL}")
        tech_results = await email_tech_classifier.classify_all(tech_articles)
        tech_approved = sorted(
            (r for r in tech_results if r.approved and r.importance >= config.MIN_TECH_IMPORTANCE_SCORE),
            key=lambda r: r.importance,
            reverse=True,
        )[:config.MAX_TECH_ARTICLES]
        print(f"  Approved: {len(tech_approved)} (cap {config.MAX_TECH_ARTICLES})")

        tech_items = [
            {
                "title":      r.article.title,
                "source":     r.article.source,
                "url":        r.article.url,
                "summary":    r.article.summary[:400],
                "importance": r.importance,
                "topics":     r.topics,
                "published":  r.article.published,
            }
            for r in tech_approved
        ]

    # ── Business: reuse what already passed the WhatsApp classifier — zero
    # extra Claude calls.
    sent_log = SentLog()
    recent   = sent_log.recent_messages(config.EMAIL_LOOKBACK_HOURS)

    business_items: list[dict] = []
    for m in sorted(recent, key=lambda x: x.get("importance", 5), reverse=True):
        business_items.append({
            "title":      m.get("title", ""),
            "source":     m.get("source", ""),
            "url":        m.get("url", ""),
            "summary":    m.get("message", ""),  # already-composed WhatsApp text — usable as a summary
            "importance": m.get("importance", 5),
            "topics":     m.get("topics", []),
            "tag":        m.get("tag", ""),
        })

    digest = {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "lookback_hours": config.EMAIL_LOOKBACK_HOURS,
        "world":          world_items,
        "business":       business_items,
        "tech":           tech_items,
    }
    config.EMAIL_DIGEST_PATH.write_text(
        json.dumps(digest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"\n  {Fore.GREEN}✓ email_digest.json written — "
        f"world: {len(world_items)} | business: {len(business_items)} | tech: {len(tech_items)}"
        f"{Style.RESET_ALL}"
    )
    _print_cost()


# ── CLI ────────────────────────────────────────────────────────────────────

async def run_check_feeds() -> None:
    """Fetch all feeds and report status without any filtering or Claude calls."""
    print(f"\n{Fore.CYAN}📡 Checking feeds…{Style.RESET_ALL}\n")
    statuses = await feeds.check_feeds()

    col = 32
    for s in statuses:
        if s.ok:
            bar = Fore.GREEN + "✓" + Style.RESET_ALL
            detail = f"{s.count} article(s)"
        else:
            bar = Fore.RED + "✗" + Style.RESET_ALL
            detail = Fore.RED + s.error[:60] + Style.RESET_ALL
        print(f"  {bar} {s.name:<{col}} {detail}")

    working = sum(1 for s in statuses if s.ok)
    total   = len(statuses)
    total_articles = sum(s.count for s in statuses)
    color = Fore.GREEN if working == total else Fore.YELLOW
    print(f"\n  {color}Working feeds: {working}/{total} | Total articles: {total_articles}{Style.RESET_ALL}")


async def run_test(args: argparse.Namespace) -> None:
    """Send args.test directly to WhatsApp — no feeds, no Claude."""
    config.validate_provider(args.provider)
    text = args.test.strip()
    if not text:
        print(f"  {Fore.RED}--test message is empty.{Style.RESET_ALL}")
        return

    print(f"\n{Fore.CYAN}🧪 Test mode — sending message directly via {args.provider}{Style.RESET_ALL}")
    print(f"{'─'*60}")
    print(f"  {Fore.GREEN}{text}{Style.RESET_ALL}")
    print(f"{'─'*60}")
    await _send([text], args.provider, skip_filter=True)
    print(f"\n  {Fore.GREEN}✓ Test message sent.{Style.RESET_ALL}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Market WhatsApp Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--auto",           action="store_true", help="Send without confirmation")
    parser.add_argument("--dry-run",        action="store_true", help="Preview only, do not send")
    parser.add_argument("--morning-digest", action="store_true", help="Send digest of recent articles")
    parser.add_argument("--provider",       choices=["twilio", "green"], default=config.DEFAULT_PROVIDER)
    parser.add_argument("--skip-humanizer", action="store_true", help="Skip style rewriting")
    parser.add_argument("--ab",             action="store_true", help="Show before/after humanizer")
    parser.add_argument("--test",           metavar="MESSAGE",   help="Send MESSAGE directly, skip all feeds")
    parser.add_argument("--check-feeds",   action="store_true", help="Check which feeds are working, no Claude")
    parser.add_argument("--collect-email-pool", action="store_true",
                         help="Fetch world feeds + recent WhatsApp-approved items into email_digest.json (no sending)")
    return parser


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    try:
        if args.check_feeds:
            asyncio.run(run_check_feeds())
        elif args.collect_email_pool:
            asyncio.run(run_collect_email_pool(args))
        elif args.test is not None:
            asyncio.run(run_test(args))
        elif args.morning_digest:
            asyncio.run(run_morning_digest(args))
        else:
            asyncio.run(run(args))
    except KeyboardInterrupt:
        print(f"\n  {Fore.YELLOW}Interrupted.{Style.RESET_ALL}")
        sys.exit(130)
    except EnvironmentError as exc:
        print(f"\n  {Fore.RED}Config error: {exc}{Style.RESET_ALL}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  {Fore.RED}Error: {exc}{Style.RESET_ALL}")
        raise


if __name__ == "__main__":
    main()
