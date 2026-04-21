"""Shared run statistics — Claude API token usage and cost tracking."""
from __future__ import annotations

# USD per million tokens, by model family
_MODEL_PRICES: dict[str, dict[str, float]] = {
    "haiku":  {"in": 0.80,  "out": 4.00},
    "sonnet": {"in": 3.00,  "out": 15.00},
}

_buckets: dict[str, dict[str, int]] = {
    "haiku":  {"input": 0, "output": 0, "calls": 0},
    "sonnet": {"input": 0, "output": 0, "calls": 0},
}


def _bucket_name(model: str) -> str:
    return "haiku" if "haiku" in model.lower() else "sonnet"


def record(input_tokens: int, output_tokens: int, model: str = "") -> None:
    b = _bucket_name(model)
    _buckets[b]["input"]  += input_tokens
    _buckets[b]["output"] += output_tokens
    _buckets[b]["calls"]  += 1


def reset() -> None:
    for b in _buckets.values():
        b.update(input=0, output=0, calls=0)


def summary() -> str:
    total_cost  = 0.0
    total_calls = 0
    total_in    = 0
    total_out   = 0
    lines: list[str] = []

    for name, b in _buckets.items():
        if b["calls"] == 0:
            continue
        p    = _MODEL_PRICES[name]
        cost = (b["input"] / 1_000_000 * p["in"]) + (b["output"] / 1_000_000 * p["out"])
        total_cost  += cost
        total_calls += b["calls"]
        total_in    += b["input"]
        total_out   += b["output"]
        lines.append(
            f"    {name}: {b['calls']} calls | "
            f"{b['input']:,}in / {b['output']:,}out | ${cost:.4f}"
        )

    header = (
        f"API calls: {total_calls} | "
        f"Tokens: {total_in:,}in / {total_out:,}out | "
        f"Est. cost: ${total_cost:.4f}"
    )
    return header + ("\n" + "\n".join(lines) if len(lines) > 1 else "")


def totals() -> dict:
    total_cost  = 0.0
    total_calls = 0
    total_in    = 0
    total_out   = 0
    for name, b in _buckets.items():
        p = _MODEL_PRICES[name]
        total_cost  += (b["input"] / 1_000_000 * p["in"]) + (b["output"] / 1_000_000 * p["out"])
        total_calls += b["calls"]
        total_in    += b["input"]
        total_out   += b["output"]
    return {
        "calls":    total_calls,
        "input":    total_in,
        "output":   total_out,
        "cost_usd": round(total_cost, 6),
    }
