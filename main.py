#!/usr/bin/env python3
"""
Market WhatsApp Bot — RSS → Claude filter → WhatsApp

Usage:
  python main.py                     # preview + manual confirm
  python main.py --auto              # send without asking
  python main.py --dry-run           # preview only, no send
  python main.py --morning-digest    # send a digest of recent articles
  python main.py --provider green    # use Green API instead of Twilio
  python main.py --skip-humanizer    # skip style rewriting
  python main.py --ab                # show before/after humanizer
"""
from __future__ import annotations

import asyncio
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import colorama
from colorama import Fore, Style

import config
import feeds
import classifier
import composer
import humanizer

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
        return {"hashes": {}, "messages": []}

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
                "message":    r.final_message,
                "importance": r.importance,
                "tag":        r.tag,
                "topics":     r.topics,
            })
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


# ── Sending ────────────────────────────────────────────────────────────────

async def _send(messages: list[str], provider: str) -> None:
    if provider == "twilio":
        import whatsapp_twilio as wa
        sids = await wa.send_all(messages)
        for sid in sids:
            print(f"  {Fore.GREEN}✓ Sent via Twilio — SID: {sid}{Style.RESET_ALL}")
    elif provider == "green":
        import whatsapp_green as wa
        responses = await wa.send_all(messages)
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


def _confirm() -> bool:
    answer = input(f"\n  {Style.BRIGHT}שלח? (y/n): {Style.RESET_ALL}").strip().lower()
    return answer in {"y", "yes", "כן", "י"}


# ── Main pipeline ──────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    config.validate_claude()
    if not args.dry_run:
        config.validate_provider(args.provider)

    sent_log = SentLog()

    # ── 1. Fetch feeds ──────────────────────────────────────────────────
    print(f"\n{Fore.CYAN}📡 Fetching RSS feeds…{Style.RESET_ALL}")
    all_articles = await feeds.fetch_all()
    print(f"  Total fetched: {len(all_articles)}")

    # ── 2. Deduplicate ──────────────────────────────────────────────────
    new_articles = [a for a in all_articles if not sent_log.is_sent(a.hash)]
    print(f"  New (not yet sent): {len(new_articles)}")

    if not new_articles:
        print(f"\n  {Fore.YELLOW}Nothing new to process.{Style.RESET_ALL}")
        return

    # ── 3. Classify ─────────────────────────────────────────────────────
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
        return

    # ── 4. Topic deduplication (72h window) ─────────────────────────────
    recent_sent = sent_log.recent_messages(72)
    if recent_sent:
        print(f"\n{Fore.CYAN}🔍 Topic dedup — checking against {len(recent_sent)} article(s) from last 72h…{Style.RESET_ALL}")
        before = len(approved)
        approved = await classifier.topic_dedup_filter(approved, recent_sent)
        skipped = before - len(approved)
        if skipped:
            print(f"  Skipped {skipped} duplicate topic(s)")
        if not approved:
            print(f"\n  {Fore.YELLOW}All approved articles were duplicates of recent topics.{Style.RESET_ALL}")
            return

    # ── 5. Compose messages ─────────────────────────────────────────────
    print(f"\n{Fore.CYAN}✍️  Composing {len(approved)} message(s)…{Style.RESET_ALL}")
    await composer.compose_all(approved)

    # ── 6. Humanizer (optional) ─────────────────────────────────────────
    profile = None
    if not args.skip_humanizer:
        profile = humanizer.load_profile()
        if profile:
            print(f"\n{Fore.CYAN}🎨 Humanizing messages…{Style.RESET_ALL}")
            await humanizer.humanize_all(approved, profile=profile)
        else:
            print(f"  {Fore.YELLOW}[humanizer] No style_profile.json found — skipping.{Style.RESET_ALL}")

    # ── 7. Sort by importance ───────────────────────────────────────────
    approved.sort(key=lambda r: r.importance, reverse=True)

    # ── 8. Preview ──────────────────────────────────────────────────────
    _preview_results(approved, show_ab=args.ab)

    if args.dry_run:
        print(f"\n  {Fore.YELLOW}--dry-run: nothing sent.{Style.RESET_ALL}")
        return

    # ── 9. Send ─────────────────────────────────────────────────────────
    if not args.auto:
        if not _confirm():
            print(f"\n  {Fore.YELLOW}Cancelled.{Style.RESET_ALL}")
            return

    print(f"\n{Fore.CYAN}📤 Sending via {args.provider}…{Style.RESET_ALL}")
    messages_to_send = [r.final_message for r in approved if r.final_message]
    await _send(messages_to_send, args.provider)

    sent_log.mark_sent(approved)
    print(f"\n  {Fore.GREEN}✓ Done — {len(messages_to_send)} message(s) sent, log updated.{Style.RESET_ALL}")


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

    await _send([digest_text], args.provider)
    print(f"\n  {Fore.GREEN}✓ Digest sent.{Style.RESET_ALL}")


# ── CLI ────────────────────────────────────────────────────────────────────

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
    return parser


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    try:
        if args.morning_digest:
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
