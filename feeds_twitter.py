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
    if not tweets:
        print("  [twitter] 0 new tweet(s)")
        return [], None

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
    return articles, None
