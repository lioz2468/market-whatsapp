#!/usr/bin/env python3
"""
Send the daily morning brief (markets + world + business + tech) to a
WhatsApp group — replaces the parked Responder/email newsletter plan
(see README: "רב מסר" V1 messaging is being retired, V2.0 has no send
endpoint). Reuses email_digest.json + the existing WhatsApp send path
(whatsapp_twilio.py / whatsapp_green.py), same as main.py's per-article bot.

Usage:
  python send_morning_brief.py                # preview + manual confirm
  python send_morning_brief.py --auto          # send without asking
  python send_morning_brief.py --dry-run       # preview only, no send
  python send_morning_brief.py --provider green

Setup: create a WhatsApp group for "בריף בוקר" subscribers, add the bot's
number to it, then set MORNING_BRIEF_TO in .env to its chat ID (Green API
group format: 123456789-123456789@g.us — see README's "הגדרת WhatsApp").
Falls back to WHATSAPP_TO if MORNING_BRIEF_TO isn't set.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import colorama
from colorama import Fore, Style

import config
import market_data
import morning_brief_composer
import stats
import watchlist_news

colorama.init(autoreset=True)

_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
_STATE_PATH = Path(__file__).resolve().parent / "morning_brief_log.json"


def _today_israel() -> str:
    return datetime.now(_ISRAEL_TZ).date().isoformat()


def _already_sent_today() -> bool:
    """True once a brief already went out today — guards the redundant
    repository_dispatch backup trigger (see send-morning-brief.yml) from
    causing a second send if the primary `schedule` firing also succeeds."""
    if not _STATE_PATH.exists():
        return False
    try:
        state = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return state.get("last_sent_date") == _today_israel()


def _mark_sent_today() -> None:
    _STATE_PATH.write_text(
        json.dumps({"last_sent_date": _today_israel()}, indent=2),
        encoding="utf-8",
    )


def _load_history() -> list[dict]:
    if not config.MORNING_BRIEF_HISTORY_PATH.exists():
        return []
    try:
        return json.loads(config.MORNING_BRIEF_HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _record_history(digest: dict, watchlist_items: list[watchlist_news.TickerNews] | None = None) -> None:
    """Append today's world/business/tech items — and watchlist headlines —
    to morning_brief_history.json (pruned to MORNING_BRIEF_HISTORY_DAYS) so
    tomorrow's cross-day dedup can see them — see
    morning_brief_composer.cross_day_dedup_filter."""
    history = _load_history()
    today   = _today_israel()
    for section in ("world", "business", "tech"):
        for it in digest.get(section, []):
            history.append({
                "date":   today,
                "title":  it.get("title", ""),
                "topics": it.get("topics", []),
            })
    for t in (watchlist_items or []):
        for h in t.headlines:
            history.append({
                "date":   today,
                "title":  h.title,
                "topics": [t.symbol],
            })

    cutoff  = (datetime.now(_ISRAEL_TZ) - timedelta(days=config.MORNING_BRIEF_HISTORY_DAYS)).date().isoformat()
    pruned  = [h for h in history if h.get("date", "") >= cutoff]
    config.MORNING_BRIEF_HISTORY_PATH.write_text(
        json.dumps(pruned, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _strip_watchlist_from_business(digest: dict) -> None:
    """A watchlist company's news belongs only in "מניות הבית" (see
    morning_brief_composer._SYSTEM_BASE section 5) — enforced here in code,
    not just prompted, so it's guaranteed rather than best-effort. Mutates
    digest["business"] in place."""
    business = digest.get("business", [])
    if not business or not config.WATCHLIST_STOCKS:
        return

    needles: list[re.Pattern] = []
    for w in config.WATCHLIST_STOCKS:
        needles.append(re.compile(rf"\b{re.escape(w['symbol'])}\b", re.IGNORECASE))
        needles.append(re.compile(rf"\b{re.escape(w['name'])}\b", re.IGNORECASE))

    kept = [it for it in business if not any(p.search(it.get("title", "")) for p in needles)]
    dropped = len(business) - len(kept)
    if dropped:
        print(
            f"  {Fore.YELLOW}Business: dropped {dropped} watchlist-company item(s) "
            f"— belongs only in מניות הבית{Style.RESET_ALL}"
        )
    digest["business"] = kept


def _is_shabbat() -> bool:
    """True from Friday 17:00 through Saturday (Israel time). Unlike main.py's
    gate this does NOT extend to Sunday 09:00 — the brief's 08:34 run falls
    inside that window, so every Sunday brief was blocked and only went out
    hours later via the backup trigger (13:41 on 2026-09-27)."""
    now = datetime.now(_ISRAEL_TZ)
    wd  = now.weekday()   # Friday=4, Saturday=5
    return (wd == 4 and now.hour >= 17) or wd == 5


# email-digest-pool.yml's 06:00 schedule routinely fires hours late
# (08:20-09:07 UTC in practice), so at 08:34 the brief was reading
# yesterday's digest — the same stories as the previous brief. Refresh it
# here when it's older than this.
_MAX_DIGEST_AGE = timedelta(hours=6)


def _refresh_digest_if_stale() -> None:
    generated_at = None
    if config.EMAIL_DIGEST_PATH.exists():
        try:
            digest = json.loads(config.EMAIL_DIGEST_PATH.read_text(encoding="utf-8"))
            generated_at = datetime.fromisoformat(digest["generated_at"])
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            pass
    if generated_at and datetime.now(generated_at.tzinfo) - generated_at < _MAX_DIGEST_AGE:
        return

    print(f"\n{Fore.CYAN}🔄 email_digest.json is stale ({generated_at or 'missing'}) — collecting a fresh one…{Style.RESET_ALL}")
    result = subprocess.run([sys.executable, "main.py", "--collect-email-pool"], cwd=Path(__file__).resolve().parent)
    if result.returncode != 0:
        print(f"  {Fore.YELLOW}⚠ Collection failed (exit {result.returncode}) — using the existing digest{Style.RESET_ALL}")


async def _compose() -> tuple[str, dict, list[watchlist_news.TickerNews]]:
    if not config.EMAIL_DIGEST_PATH.exists():
        print(
            f"  {Fore.RED}email_digest.json not found — run "
            f"`python main.py --collect-email-pool` first.{Style.RESET_ALL}"
        )
        sys.exit(1)
    digest = json.loads(config.EMAIL_DIGEST_PATH.read_text(encoding="utf-8"))
    _strip_watchlist_from_business(digest)

    if config.WATCHLIST_STOCKS:
        print(f"\n{Fore.CYAN}📈 Fetching watchlist news ({len(config.WATCHLIST_STOCKS)} ticker(s))…{Style.RESET_ALL}")
    watchlist_items = await watchlist_news.fetch_watchlist_news(config.WATCHLIST_STOCKS)

    history = _load_history()
    if history:
        combined = [
            {**it, "_section": section}
            for section in ("world", "business", "tech")
            for it in digest.get(section, [])
        ] + [
            {"title": h.title, "topics": [t.symbol], "_section": "watchlist", "_symbol": t.symbol, "_headline": h}
            for t in watchlist_items
            for h in t.headlines
        ]
        print(
            f"\n{Fore.CYAN}🔍 Cross-day dedup — checking {len(combined)} item(s) against "
            f"{len(history)} sent in the last {config.MORNING_BRIEF_HISTORY_DAYS}d…{Style.RESET_ALL}"
        )
        filtered = await morning_brief_composer.cross_day_dedup_filter(combined, history)
        if len(filtered) != len(combined):
            print(f"  {Fore.YELLOW}Filtered {len(combined) - len(filtered)} already-covered item(s){Style.RESET_ALL}")
        for section in ("world", "business", "tech"):
            digest[section] = [it for it in filtered if it["_section"] == section]
        kept_by_symbol: dict[str, list] = {}
        for it in filtered:
            if it["_section"] == "watchlist":
                kept_by_symbol.setdefault(it["_symbol"], []).append(it["_headline"])
        for t in watchlist_items:
            t.headlines = kept_by_symbol.get(t.symbol, [])

    watchlist_text = watchlist_news.format_watchlist_for_prompt(watchlist_items)

    print(f"\n{Fore.CYAN}📊 Fetching market snapshot…{Style.RESET_ALL}")
    quotes = await market_data.fetch_snapshot()
    for q in quotes:
        mark = f"{Fore.GREEN}✓{Style.RESET_ALL}" if q.ok else f"{Fore.RED}✗{Style.RESET_ALL}"
        detail = f"{q.price:,.2f}" if q.ok else q.error[:60]
        print(f"  {mark} {q.name:<10} {detail}")
    market_text = market_data.format_snapshot_for_prompt(quotes)

    print(f"\n{Fore.CYAN}✍️  Composing morning brief with Claude…{Style.RESET_ALL}")
    text = await morning_brief_composer.compose_morning_brief(digest, market_text, watchlist_text, history)
    print(f"  {Fore.GREEN}✓ {len(text)} chars, {len(text.splitlines())} lines{Style.RESET_ALL}")
    return text, digest, watchlist_items


def _print_cost() -> None:
    t = stats.totals()
    if t["calls"]:
        print(f"\n  {Fore.YELLOW}{stats.summary()}{Style.RESET_ALL}")


def _confirm() -> bool:
    answer = input(f"\n  {Style.BRIGHT}שלח לקבוצה? (y/n): {Style.RESET_ALL}").strip().lower()
    return answer in {"y", "yes", "כן", "י"}


async def main_async(args: argparse.Namespace) -> None:
    config.validate_claude()
    if not args.dry_run:
        config.validate_whatsapp_credentials(args.provider)

    if not args.dry_run and not args.force and _already_sent_today():
        print(f"\n  {Fore.YELLOW}⏭  Already sent today — skipping (use --force to override).{Style.RESET_ALL}")
        return

    if not args.dry_run and _is_shabbat():
        print(f"\n  {Fore.YELLOW}⛔ שבת — שליחה מושהית עד ראשון (שעון ישראל).{Style.RESET_ALL}")
        return

    _refresh_digest_if_stale()
    text, digest, watchlist_items = await _compose()
    _print_cost()

    print(f"\n{'─'*60}\n{Fore.GREEN}{text}{Style.RESET_ALL}\n{'─'*60}")

    if args.dry_run:
        print(f"\n  {Fore.YELLOW}--dry-run: nothing sent.{Style.RESET_ALL}")
        return

    if not config.MORNING_BRIEF_TO:
        print(
            f"  {Fore.RED}MORNING_BRIEF_TO (or WHATSAPP_TO) is not set — "
            f"point it at your WhatsApp group's chat ID.{Style.RESET_ALL}"
        )
        sys.exit(1)

    if not args.auto and not _confirm():
        print(f"\n  {Fore.YELLOW}Cancelled.{Style.RESET_ALL}")
        return

    print(f"\n{Fore.CYAN}📤 Sending via {args.provider}…{Style.RESET_ALL}")
    if args.provider == "twilio":
        import whatsapp_twilio as wa
        sids = await wa.send_all([text], to=config.MORNING_BRIEF_TO)
        for sid in sids:
            print(f"  {Fore.GREEN}✓ Sent via Twilio — SID: {sid}{Style.RESET_ALL}")
    else:
        import whatsapp_green as wa
        responses = await wa.send_all([text], to=config.MORNING_BRIEF_TO)
        for resp in responses:
            mid = resp.get("idMessage", "?")
            print(f"  {Fore.GREEN}✓ Sent via Green API — id: {mid}{Style.RESET_ALL}")

    _mark_sent_today()
    _record_history(digest, watchlist_items)
    print(f"\n  {Fore.GREEN}✓ Done.{Style.RESET_ALL}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send the daily morning brief to a WhatsApp group",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--auto",     action="store_true", help="Send without confirmation")
    parser.add_argument("--dry-run",  action="store_true", help="Preview only, do not send")
    parser.add_argument("--force",    action="store_true", help="Send even if already sent today")
    parser.add_argument("--provider", choices=["twilio", "green"], default=config.DEFAULT_PROVIDER)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print(f"\n  {Fore.YELLOW}Interrupted.{Style.RESET_ALL}")
        sys.exit(130)
    except EnvironmentError as exc:
        print(f"\n  {Fore.RED}Config error: {exc}{Style.RESET_ALL}")
        sys.exit(1)


if __name__ == "__main__":
    main()
