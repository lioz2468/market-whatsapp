#!/usr/bin/env python3
"""
Style Extractor CLI
Usage:
  python main.py ingest                     # transcribe + process content
  python main.py analyze                    # analyze style with Claude
  python main.py validate                   # show summary + confirm save
  python main.py all                        # full pipeline
  python main.py ingest --skip-diarization  # transcribe without speaker ID
  python main.py test "הפד הוריד ריבית"    # generate text in your style
"""
from __future__ import annotations

import argparse
import sys
import time

# ─────────────────────────────────────────────────────────────────────────────


def cmd_ingest(args: argparse.Namespace) -> None:
    from ingest.audio       import ingest_podcasts
    from ingest.text_reader import ingest_posts, ingest_whatsapp, ingest_tweets

    print("\n🎙️  INGEST — Processing source material")
    print("─" * 50)

    podcast_results = ingest_podcasts(skip_diarization=args.skip_diarization)
    post_results    = ingest_posts()
    wa_results      = ingest_whatsapp()
    tweet_results   = ingest_tweets()

    total = len(podcast_results) + len(post_results) + len(wa_results) + len(tweet_results)
    print(f"\n  ✓ Ingested {total} item(s): "
          f"{len(podcast_results)} podcast(s), "
          f"{len(post_results)} post(s), "
          f"{len(wa_results)} WhatsApp export(s), "
          f"{len(tweet_results)} tweet file(s).")
    print("  Processed files saved to: processed/")


def cmd_analyze(args: argparse.Namespace) -> None:
    from analyzer.style_analyzer  import analyze_all_content
    from analyzer.profile_builder import build_draft_profile, validate_and_save

    print("\n🧠  ANALYZE — Style analysis with Claude")
    print("─" * 50)

    t0 = time.time()
    analyses = analyze_all_content()
    print(f"\n  ✓ Analyzed {len(analyses)} chunk(s) in {time.time()-t0:.1f}s")

    profile = build_draft_profile(analyses)

    # Immediately go to validate
    validate_and_save(profile)


def cmd_validate(args: argparse.Namespace) -> None:
    from analyzer.profile_builder import validate_and_save
    import json
    import config

    print("\n✅  VALIDATE — Review and confirm style profile")
    print("─" * 50)

    if not config.DRAFT_PATH.exists():
        print(f"  No draft profile found at {config.DRAFT_PATH}")
        print("  Run `python main.py analyze` first.")
        sys.exit(1)

    profile = json.loads(config.DRAFT_PATH.read_text(encoding="utf-8"))
    validate_and_save(profile)


def cmd_all(args: argparse.Namespace) -> None:
    cmd_ingest(args)
    cmd_analyze(args)


def cmd_test(args: argparse.Namespace) -> None:
    from analyzer.profile_builder import load_profile, generate_test_text
    import config

    topic = args.topic
    print(f"\n🖊️  TEST — Generating text about: '{topic}'")
    print("─" * 50)

    try:
        profile = load_profile()
    except FileNotFoundError as e:
        print(f"  Error: {e}")
        sys.exit(1)

    print()
    generate_test_text(topic, profile)


# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Style Extractor — build your personal writing/speaking profile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Transcribe podcasts and read posts")
    p_ingest.add_argument(
        "--skip-diarization",
        action="store_true",
        help="Skip speaker identification (faster, no GPU needed)",
    )

    # analyze
    sub.add_parser("analyze", help="Analyze style with Claude and build profile")

    # validate
    sub.add_parser("validate", help="Review draft profile and confirm save")

    # all
    p_all = sub.add_parser("all", help="Run full pipeline: ingest → analyze → validate")
    p_all.add_argument(
        "--skip-diarization",
        action="store_true",
        help="Skip speaker identification during ingest",
    )

    # test
    p_test = sub.add_parser("test", help="Generate a text in your style")
    p_test.add_argument("topic", help='Topic to write about, e.g. "הפד הוריד ריבית"')

    return parser


def main() -> None:
    parser  = _build_parser()
    args    = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Ensure --skip-diarization exists on all namespaces
    if not hasattr(args, "skip_diarization"):
        args.skip_diarization = False

    try:
        dispatch = {
            "ingest":   cmd_ingest,
            "analyze":  cmd_analyze,
            "validate": cmd_validate,
            "all":      cmd_all,
            "test":     cmd_test,
        }
        dispatch[args.command](args)

    except KeyboardInterrupt:
        print("\n\n  Interrupted.")
        sys.exit(130)
    except Exception as exc:
        print(f"\n  ❌ Error: {exc}")
        raise


if __name__ == "__main__":
    main()
