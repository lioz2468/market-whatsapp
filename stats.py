"""Shared run statistics — Claude API token usage and cost tracking."""
from __future__ import annotations

# USD per million tokens, by model family
_MODEL_PRICES: dict[str, dict[str, float]] = {
    "haiku":  {"in": 0.80,  "out": 4.00},
    "sonnet": {"in": 3.00,  "out": 15.00},
}
# Prompt-cache multipliers on the input price: writes cost 1.25x, reads 0.1x.
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT  = 0.10

_buckets: dict[str, dict[str, int]] = {
    "haiku":  {"input": 0, "output": 0, "calls": 0, "cache_write": 0, "cache_read": 0},
    "sonnet": {"input": 0, "output": 0, "calls": 0, "cache_write": 0, "cache_read": 0},
}


def _bucket_name(model: str) -> str:
    return "haiku" if "haiku" in model.lower() else "sonnet"


def _bucket_cost(name: str, b: dict[str, int]) -> float:
    p = _MODEL_PRICES[name]
    return (
        b["input"] / 1_000_000 * p["in"]
        + b["cache_write"] / 1_000_000 * p["in"] * _CACHE_WRITE_MULT
        + b["cache_read"]  / 1_000_000 * p["in"] * _CACHE_READ_MULT
        + b["output"] / 1_000_000 * p["out"]
    )


def record(
    input_tokens: int,
    output_tokens: int,
    model: str = "",
    cache_write: int = 0,
    cache_read: int = 0,
) -> None:
    """input_tokens is the uncached part only (as the API reports it);
    cached tokens are passed separately so they're priced correctly."""
    b = _bucket_name(model)
    _buckets[b]["input"]       += input_tokens
    _buckets[b]["output"]      += output_tokens
    _buckets[b]["cache_write"] += cache_write
    _buckets[b]["cache_read"]  += cache_read
    _buckets[b]["calls"]       += 1


def reset() -> None:
    for b in _buckets.values():
        b.update(input=0, output=0, calls=0, cache_write=0, cache_read=0)


def summary() -> str:
    total_cost  = 0.0
    total_calls = 0
    total_in    = 0
    total_out   = 0
    total_cached = 0
    lines: list[str] = []

    for name, b in _buckets.items():
        if b["calls"] == 0:
            continue
        cost = _bucket_cost(name, b)
        total_cost  += cost
        total_calls += b["calls"]
        total_in    += b["input"]
        total_out   += b["output"]
        total_cached += b["cache_write"] + b["cache_read"]
        cache_note = (
            f" (+cache {b['cache_write']:,}w / {b['cache_read']:,}r)"
            if b["cache_write"] or b["cache_read"] else ""
        )
        lines.append(
            f"    {name}: {b['calls']} calls | "
            f"{b['input']:,}in / {b['output']:,}out{cache_note} | ${cost:.4f}"
        )

    header = (
        f"API calls: {total_calls} | "
        f"Tokens: {total_in:,}in / {total_out:,}out | "
        f"Est. cost: ${total_cost:.4f}"
    )
    show_lines = len(lines) > 1 or total_cached
    return header + ("\n" + "\n".join(lines) if show_lines else "")


def totals() -> dict:
    total_cost  = 0.0
    total_calls = 0
    total_in    = 0
    total_out   = 0
    for name, b in _buckets.items():
        total_cost  += _bucket_cost(name, b)
        total_calls += b["calls"]
        total_in    += b["input"]
        total_out   += b["output"]
    return {
        "calls":    total_calls,
        "input":    total_in,
        "output":   total_out,
        "cost_usd": round(total_cost, 6),
    }
