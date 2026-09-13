"""X (Twitter) API v2 feed source for @wallstengine — replaces the dead Nitter RSS mirrors.

Uses GET /2/users/:id/tweets with since_id so each run only pulls tweets newer
than the last one seen. The resolved user id and the last-seen tweet id are
persisted in twitter_last_id.json (committed back to the repo by the GitHub
Actions workflow, the same way sent_log.json is).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests

import config

API_BASE     = "https://api.twitter.com/2"
USERNAME     = "wallstengine"
LAST_ID_PATH = config.BASE_DIR / "twitter_last_id.json"
MAX_RESULTS  = 15
TIMEOUT      = 15


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


def _resolve_user_id(token: str, state: dict) -> Optional[str]:
    """Look up @wallstengine's numeric user id once, then cache it in state."""
    if state.get("user_id"):
        return state["user_id"]

    try:
        resp = requests.get(
            f"{API_BASE}/users/by/username/{USERNAME}",
            headers=_headers(token),
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        print(f"  [twitter] ✗ network error resolving user id: {e}")
        return None

    if resp.status_code == 401:
        print("  [twitter] ✗ auth error (401) resolving user id — check X_BEARER_TOKEN")
        return None
    if resp.status_code == 429:
        print("  [twitter] ✗ rate limited (429) resolving user id")
        return None
    if resp.status_code != 200:
        print(f"  [twitter] ✗ unexpected status {resp.status_code} resolving user id: {resp.text[:200]}")
        return None

    user_id = (resp.json().get("data") or {}).get("id")
    if not user_id:
        print(f"  [twitter] ✗ user '@{USERNAME}' not found")
        return None

    state["user_id"] = user_id
    _save_state(state)
    return user_id


def fetch_tweets() -> list[dict]:
    """Fetch tweets from @wallstengine newer than the last-seen tweet.

    Returns a list of dicts with keys: id, title, url, summary, published,
    source, lang — the same shape feeds.py turns RSS entries into.

    Never raises: returns [] if X_BEARER_TOKEN is unset (silent skip), or on
    any auth/rate-limit/network/API error (logged to stdout).
    """
    token = config.X_BEARER_TOKEN
    if not token:
        return []

    state   = _load_state()
    user_id = _resolve_user_id(token, state)
    if not user_id:
        return []

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
        print(f"  [twitter] ✗ network error fetching tweets: {e}")
        return []

    if resp.status_code == 401:
        print("  [twitter] ✗ auth error (401) — check X_BEARER_TOKEN")
        return []
    if resp.status_code == 429:
        reset = resp.headers.get("x-rate-limit-reset", "")
        suffix = f" — resets at epoch {reset}" if reset else ""
        print(f"  [twitter] ✗ rate limited (429){suffix}")
        return []
    if resp.status_code != 200:
        print(f"  [twitter] ✗ unexpected status {resp.status_code}: {resp.text[:200]}")
        return []

    tweets = resp.json().get("data") or []
    if not tweets:
        print("  [twitter] 0 new tweet(s)")
        return []

    # Twitter returns newest-first; the first item becomes the new watermark.
    state["last_id"] = tweets[0]["id"]
    _save_state(state)

    articles = [
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

    print(f"  [twitter] {len(articles)} new tweet(s)")
    return articles
