"""X (Twitter) API v2 feed source for @wallstengine — replaces the dead Nitter RSS mirrors.

Uses GET /2/users/:id/tweets with since_id so each run only pulls tweets newer
than the last one seen. The resolved user id and the last-seen tweet id are
persisted in twitter_last_id.json (committed back to the repo by the GitHub
Actions workflow, the same way sent_log.json is).

Tweets fetched but not sent/queued by main.py are saved to
twitter_unused.json (see save_unused()/load_unused()) and re-offered as
candidates on the next fetch — otherwise since_id would make them
unrecoverable the moment a tweet isn't picked, even if it was genuinely good
content that just lost out to something else that run.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

import config

API_BASE       = "https://api.twitter.com/2"
USERNAME       = "wallstengine"
LAST_ID_PATH   = config.BASE_DIR / "twitter_last_id.json"
UNUSED_PATH    = config.BASE_DIR / "twitter_unused.json"
MAX_RESULTS    = 15
TIMEOUT        = 15
UNUSED_MAX_AGE_HOURS = 24
UNUSED_MAX_COUNT     = 30


def _load_state() -> dict:
    if LAST_ID_PATH.exists():
        try:
            return json.loads(LAST_ID_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    LAST_ID_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def load_unused() -> list[dict]:
    """Tweets fetched in a previous run that weren't sent or queued — offered
    again as candidates so they get a real second chance before being lost
    for good (since_id never lets the live API return them again)."""
    if not UNUSED_PATH.exists():
        return []
    try:
        return json.loads(UNUSED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_unused(tweets: list[dict]) -> None:
    """Persist the tweets a run considered but didn't end up sending/queuing.
    Pruned by age (a stale tweet isn't worth resurfacing) and capped in size."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=UNUSED_MAX_AGE_HOURS)
    fresh: list[dict] = []
    for t in tweets:
        try:
            published = datetime.fromisoformat(t["published"].replace("Z", "+00:00"))
        except Exception:
            continue
        if published >= cutoff:
            fresh.append(t)
    fresh = fresh[:UNUSED_MAX_COUNT]
    UNUSED_PATH.write_text(
        json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _merge_unique(*groups: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for group in groups:
        for item in group:
            if item["id"] not in seen:
                seen.add(item["id"])
                out.append(item)
    return out


def _resolve_user_id(token: str, state: dict) -> tuple[Optional[str], Optional[str]]:
    """Look up @wallstengine's numeric user id once, then cache it in state.

    Returns (user_id, error_message) — error_message is None on success.
    """
    if state.get("user_id"):
        return state["user_id"], None

    try:
        resp = requests.get(
            f"{API_BASE}/users/by/username/{USERNAME}",
            headers=_headers(token),
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        msg = f"network error resolving user id: {e}"
        print(f"  [twitter] ✗ {msg}")
        return None, msg

    if resp.status_code == 401:
        msg = "auth error (401) resolving user id — check X_BEARER_TOKEN"
        print(f"  [twitter] ✗ {msg}")
        return None, msg
    if resp.status_code == 429:
        msg = "rate limited (429) resolving user id"
        print(f"  [twitter] ✗ {msg}")
        return None, msg
    if resp.status_code != 200:
        msg = f"unexpected status {resp.status_code} resolving user id: {resp.text[:200]}"
        print(f"  [twitter] ✗ {msg}")
        return None, msg

    user_id = (resp.json().get("data") or {}).get("id")
    if not user_id:
        msg = f"user '@{USERNAME}' not found"
        print(f"  [twitter] ✗ {msg}")
        return None, msg

    state["user_id"] = user_id
    _save_state(state)
    return user_id, None


def fetch_tweets() -> tuple[list[dict], Optional[str]]:
    """Fetch tweets from @wallstengine newer than the last-seen tweet.

    Returns (tweets, error_message):
      - tweets: list of dicts with keys id, title, url, summary, published,
        source, lang — the same shape feeds.py turns RSS entries into.
      - error_message: None on success (even if there are simply 0 new
        tweets); otherwise a human-readable reason — X_BEARER_TOKEN unset,
        auth (401), rate limit (429), network error, or unexpected API
        response.

    Never raises. Every failure path is also printed to stdout so it shows
    up in --auto and --check-feeds runs alike.
    """
    token = config.X_BEARER_TOKEN
    if not token:
        msg = "X_BEARER_TOKEN not set — skipping Twitter feed"
        print(f"  [twitter] ⚠ {msg}")
        return [], msg

    state = _load_state()
    user_id, err = _resolve_user_id(token, state)
    if not user_id:
        return [], err

    params = {
        "max_results":  MAX_RESULTS,
        "exclude":      "replies,retweets",
        "tweet.fields": "created_at",
    }
    since_id = state.get("last_id")
    if since_id:
        params["since_id"] = since_id

    try:
        resp = requests.get(
            f"{API_BASE}/users/{user_id}/tweets",
            headers=_headers(token),
            params=params,
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        msg = f"network error fetching tweets: {e}"
        print(f"  [twitter] ✗ {msg}")
        return [], msg

    if resp.status_code == 401:
        msg = "auth error (401) — check X_BEARER_TOKEN"
        print(f"  [twitter] ✗ {msg}")
        return [], msg
    if resp.status_code == 429:
        reset  = resp.headers.get("x-rate-limit-reset", "")
        suffix = f" — resets at epoch {reset}" if reset else ""
        msg    = f"rate limited (429){suffix}"
        print(f"  [twitter] ✗ {msg}")
        return [], msg
    if resp.status_code != 200:
        msg = f"unexpected status {resp.status_code}: {resp.text[:200]}"
        print(f"  [twitter] ✗ {msg}")
        return [], msg

    tweets = resp.json().get("data") or []

    if tweets:
        # Twitter returns newest-first; the first item becomes the new watermark.
        state["last_id"] = tweets[0]["id"]
        _save_state(state)

    new_articles = [
        {
            "id":        tweet["id"],
            "title":     tweet.get("text", "").strip(),
            "url":       f"https://twitter.com/{USERNAME}/status/{tweet['id']}",
            "summary":   tweet.get("text", "").strip(),
            "published": tweet.get("created_at", ""),
            "source":    f"Twitter @{USERNAME}",
            "lang":      "en",
        }
        for tweet in tweets
        if tweet.get("text", "").strip()
    ]

    unused   = load_unused()
    combined = _merge_unique(new_articles, unused)

    print(f"  [twitter] {len(new_articles)} new tweet(s)")
    if unused:
        print(f"  [twitter] {len(unused)} previously-unused tweet(s) offered again")

    return combined, None
