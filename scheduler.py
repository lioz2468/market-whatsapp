#!/usr/bin/env python3
"""
Run the market bot every 90 minutes.

Usage:
  python scheduler.py                        # use default provider from .env
  python scheduler.py --provider green       # force Green API
  python scheduler.py --interval 60          # run every 60 minutes instead

Keep this running in the background (e.g. in a terminal or as a Windows service).
Press Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_shabbat() -> bool:
    """True from Friday 17:00 through Saturday end (Israel time)."""
    now = datetime.now(_ISRAEL_TZ)
    wd  = now.weekday()   # Friday=4, Saturday=5
    return wd == 5 or (wd == 4 and now.hour >= 17)


def run_once(provider: str | None) -> None:
    if _is_shabbat():
        print(f"[{_now()}] ⛔ שבת — דילוג על הרצה עד ראשון.")
        return

    cmd = [sys.executable, "main.py", "--auto"]
    if provider:
        cmd += ["--provider", provider]

    print(f"\n[{_now()}] ▶ Running bot…")
    result = subprocess.run(cmd, cwd=str(__file__).rsplit("\\", 1)[0])
    if result.returncode == 0:
        print(f"[{_now()}] ✓ Done (exit 0)")
    else:
        print(f"[{_now()}] ⚠ Exited with code {result.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Market bot scheduler")
    parser.add_argument("--provider", choices=["twilio", "green"], default=None,
                        help="WhatsApp provider (default: from .env)")
    parser.add_argument("--interval", type=int, default=90,
                        help="Minutes between runs (default: 90)")
    args = parser.parse_args()

    interval_sec = args.interval * 60
    print(f"Scheduler started — running every {args.interval} minutes. Ctrl+C to stop.")

    while True:
        run_once(args.provider)
        next_run = datetime.now().strftime("%H:%M")
        print(f"[{_now()}] ⏱ Next run in {args.interval} min (at ~{next_run}+{args.interval}m)")
        try:
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("\nScheduler stopped.")
            sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")
        sys.exit(0)
