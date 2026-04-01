"""Shared run statistics — Claude API token usage and cost tracking."""
from __future__ import annotations

import config

# Approximate prices for claude-sonnet models (USD per million tokens).
# Update if you switch models or Anthropic changes pricing.
_PRICE_IN  = 3.00   # $ / M input tokens
_PRICE_OUT = 15.00  # $ / M output tokens

_tokens: dict[str, int] = {"input": 0, "output": 0, "calls": 0}


def record(input_tokens: int, output_tokens: int) -> None:
    _tokens["input"]  += input_tokens
    _tokens["output"] += output_tokens
    _tokens["calls"]  += 1


def reset() -> None:
    _tokens.update(input=0, output=0, calls=0)


def summary() -> str:
    i, o, c = _tokens["input"], _tokens["output"], _tokens["calls"]
    cost = (i / 1_000_000 * _PRICE_IN) + (o / 1_000_000 * _PRICE_OUT)
    return (
        f"API calls: {c} | "
        f"Tokens: {i:,} in / {o:,} out | "
        f"Est. cost: ${cost:.4f}"
    )


def totals() -> dict:
    i, o, c = _tokens["input"], _tokens["output"], _tokens["calls"]
    cost = (i / 1_000_000 * _PRICE_IN) + (o / 1_000_000 * _PRICE_OUT)
    return {"calls": c, "input": i, "output": o, "cost_usd": cost}
