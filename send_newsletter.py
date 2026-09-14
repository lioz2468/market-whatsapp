#!/usr/bin/env python3
"""
Send the daily morning newsletter through Responder (רב מסר).

Usage:
  python send_newsletter.py                 # compose + create message + TEST send only (default, safe)
  python send_newsletter.py --dry-run        # compose only, print the HTML, no Responder calls at all
  python send_newsletter.py --send-live      # after the test is verified: also send to the real list
                                              #   (also requires NEWSLETTER_ALLOW_LIVE_SEND=true)
  python send_newsletter.py --list-lists     # GET /main/lists — use this once to find RESPONDER_LIST_ID

Safety by default:
  - Without --send-live, this NEVER sends to the real list — only a test
    send (Responder's /test endpoint) to NEWSLETTER_TEST_EMAIL
    (default: lioz2468@gmail.com).
  - --send-live additionally requires the NEWSLETTER_ALLOW_LIVE_SEND env var
    to be exactly "true" — two separate opt-ins, because an unattended real
    send goes to the whole subscriber list with no undo, and Israeli
    anti-spam law (תיקון 40) makes that a real problem, not just an
    annoyance. Flip NEWSLETTER_ALLOW_LIVE_SEND only after verifying the test
    email's content/formatting and confirming the list is genuine opt-in.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import colorama
from colorama import Fore, Style

import config
import market_data
import newsletter_composer
import responder_client
import responder_v2_client
import stats

colorama.init(autoreset=True)


async def _compose() -> tuple[str, str]:
    if not config.EMAIL_DIGEST_PATH.exists():
        print(
            f"  {Fore.RED}email_digest.json not found — run "
            f"`python main.py --collect-email-pool` first.{Style.RESET_ALL}"
        )
        sys.exit(1)
    digest = json.loads(config.EMAIL_DIGEST_PATH.read_text(encoding="utf-8"))

    print(f"\n{Fore.CYAN}📊 Fetching market snapshot…{Style.RESET_ALL}")
    quotes = await market_data.fetch_snapshot()
    for q in quotes:
        mark = f"{Fore.GREEN}✓{Style.RESET_ALL}" if q.ok else f"{Fore.RED}✗{Style.RESET_ALL}"
        detail = f"{q.price:,.2f}" if q.ok else q.error[:60]
        print(f"  {mark} {q.name:<10} {detail}")
    market_text = market_data.format_snapshot_for_prompt(quotes)

    print(f"\n{Fore.CYAN}✍️  Composing newsletter with Claude…{Style.RESET_ALL}")
    subject, html_body = await newsletter_composer.compose_newsletter(digest, market_text)
    print(f"  {Fore.GREEN}✓ Subject: {subject} ({len(html_body)} chars HTML){Style.RESET_ALL}")
    return subject, html_body


def _print_cost() -> None:
    t = stats.totals()
    if t["calls"]:
        print(f"\n  {Fore.YELLOW}{stats.summary()}{Style.RESET_ALL}")


async def main_async(args: argparse.Namespace) -> None:
    if args.list_lists_v2:
        print(f"\n{Fore.CYAN}Authenticating against Responder V2.0…{Style.RESET_ALL}")
        lists_ = await responder_v2_client.get_lists()
        if not lists_:
            print(f"  {Fore.YELLOW}No lists returned.{Style.RESET_ALL}")
            return
        print(f"\n{Fore.CYAN}Lists in your Responder account (via V2.0):{Style.RESET_ALL}")
        for l in lists_:
            print(f"  {l}")
        return

    if args.list_lists:
        config.validate_responder()
        print(f"\n{Fore.CYAN}Fetching lists from Responder…{Style.RESET_ALL}")
        lists_ = await responder_client.get_lists()
        if not lists_:
            print(f"  {Fore.YELLOW}No lists returned.{Style.RESET_ALL}")
            return
        for l in lists_:
            print(f"  ID={l.get('ID')}  NAME={l.get('NAME')}  {l.get('DESCRIPTION', '')}")
        return

    config.validate_claude()

    subject, html_body = await _compose()
    _print_cost()

    if args.dry_run:
        print(f"\n{'─'*60}\n{html_body}\n{'─'*60}")
        print(f"\n  {Fore.YELLOW}--dry-run: no Responder calls made.{Style.RESET_ALL}")
        return

    config.validate_responder()
    if not config.RESPONDER_LIST_ID:
        print(
            f"  {Fore.RED}RESPONDER_LIST_ID is not set — run "
            f"`python send_newsletter.py --list-lists` first to find it.{Style.RESET_ALL}"
        )
        sys.exit(1)

    print(f"\n{Fore.CYAN}📨 Creating message in Responder…{Style.RESET_ALL}")
    message_id = await responder_client.create_message(config.RESPONDER_LIST_ID, subject, html_body)
    print(f"  {Fore.GREEN}✓ MESSAGE_ID={message_id}{Style.RESET_ALL}")

    print(f"\n{Fore.CYAN}🧪 Sending TEST to {config.NEWSLETTER_TEST_EMAIL}…{Style.RESET_ALL}")
    ok = await responder_client.send_test(
        config.RESPONDER_LIST_ID, message_id,
        name=config.NEWSLETTER_TEST_NAME, email=config.NEWSLETTER_TEST_EMAIL,
    )
    if not ok:
        print(f"  {Fore.RED}✗ Test send reported failure — stopping before any real send.{Style.RESET_ALL}")
        sys.exit(1)
    print(f"  {Fore.GREEN}✓ Test sent — check {config.NEWSLETTER_TEST_EMAIL}.{Style.RESET_ALL}")

    if not args.send_live:
        print(
            f"\n  {Fore.YELLOW}Test-only run — nothing sent to the list. "
            f"Re-run with --send-live once you've verified the test email.{Style.RESET_ALL}"
        )
        return

    if not config.NEWSLETTER_ALLOW_LIVE_SEND:
        print(
            f"\n  {Fore.RED}--send-live was passed but NEWSLETTER_ALLOW_LIVE_SEND is not 'true' — "
            f"refusing to send to the real list. Set it explicitly once you're ready.{Style.RESET_ALL}"
        )
        sys.exit(1)

    print(
        f"\n{Fore.CYAN}📤 Sending LIVE to the list "
        f"(RESPONDER_LIST_ID={config.RESPONDER_LIST_ID})…{Style.RESET_ALL}"
    )
    sent = await responder_client.send_live(config.RESPONDER_LIST_ID, message_id)
    if sent:
        print(f"  {Fore.GREEN}✓ Newsletter sent to the list.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}✗ Live send reported failure.{Style.RESET_ALL}")
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send the daily newsletter via Responder (רב מסר)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run", action="store_true",
                         help="Compose only, print the HTML, no Responder calls")
    parser.add_argument("--send-live", action="store_true",
                         help="After a successful test send, also send to the real list "
                              "(needs NEWSLETTER_ALLOW_LIVE_SEND=true)")
    parser.add_argument("--list-lists", action="store_true",
                         help="V1: GET /main/lists and print list IDs/names, then exit "
                              "(needs RESPONDER_C_KEY/C_SECRET/U_KEY/U_SECRET from Responder support)")
    parser.add_argument("--list-lists-v2", action="store_true",
                         help="V2.0: authenticate + GET /lists via the self-service API "
                              "(needs RESPONDER_V2_CLIENT_ID/CLIENT_SECRET/USER_TOKEN) — "
                              "use this to verify credentials and find RESPONDER_LIST_ID "
                              "without waiting on the support call")
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
    except responder_client.ResponderError as exc:
        print(f"\n  {Fore.RED}Responder API error: {exc}{Style.RESET_ALL}")
        sys.exit(1)
    except responder_v2_client.ResponderV2Error as exc:
        print(f"\n  {Fore.RED}Responder V2 API error: {exc}{Style.RESET_ALL}")
        sys.exit(1)


if __name__ == "__main__":
    main()
