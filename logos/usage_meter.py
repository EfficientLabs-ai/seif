#!/usr/bin/env python3
"""Token + cost accounting for the SEIF loop — the one place that turns a `claude -p` result into numbers.

The whole point: every model call the loop makes should be cost-attributable, so a token/USD claim can be
MEASURED instead of asserted. This is a pure, dependency-free primitive shared by BOTH the production loop
(seif_run) and the eval arms — parse a `claude -p --output-format json` envelope into a normalized usage
dict, and accumulate per-attempt usage across a task. Instrumentation must NEVER break a run, so every
parse failure degrades to zeros rather than raising.

`claude -p --output-format json` emits a result envelope carrying `usage.{input_tokens, output_tokens,
cache_creation_input_tokens, cache_read_input_tokens}`, a top-level `total_cost_usd`, and `model`. Cache
classes are kept SEPARATE on purpose: cache-read tokens are near-free vs fresh input tokens, so collapsing
them into one number would let a "savings" be a caching artifact rather than a real reduction in work.
"""
import json

_TOKEN_FIELDS = ("input_tokens", "output_tokens",
                 "cache_creation_input_tokens", "cache_read_input_tokens")


def empty():
    """A zeroed accumulator — the starting point for a task's spend, and the safe value when nothing ran."""
    acc = {k: 0 for k in _TOKEN_FIELDS}
    acc["cost_usd"] = 0.0
    acc["calls"] = 0
    acc["model"] = None
    return acc


def parse_usage(stdout):
    """Extract a normalized usage dict from a `claude -p --output-format json` result envelope.

    Returns a single-call usage dict (token fields + cost_usd + model, NO `calls`). On any malformed,
    empty, or non-JSON input returns a zeroed dict — instrumentation never raises into the loop."""
    one = {k: 0 for k in _TOKEN_FIELDS}
    one["cost_usd"] = 0.0
    one["model"] = None
    try:
        obj = json.loads(stdout)
    except Exception:  # noqa: BLE001 — any non-JSON / partial output → zeros, never a crash
        return one
    if not isinstance(obj, dict):
        return one
    usage = obj.get("usage")
    if isinstance(usage, dict):
        for k in _TOKEN_FIELDS:
            v = usage.get(k)
            if isinstance(v, bool):           # guard: bools are ints in Python; never count True as 1 token
                continue
            if isinstance(v, (int, float)):
                one[k] = int(v)
    cost = obj.get("total_cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        one["cost_usd"] = float(cost)
    model = obj.get("model")
    if isinstance(model, str) and model:
        one["model"] = model
    else:
        # real `claude -p` envelopes carry no top-level `model`; the name is a key of `modelUsage`.
        mu = obj.get("modelUsage")
        if isinstance(mu, dict):
            first = next((k for k in mu if isinstance(k, str) and k), None)
            if first:
                one["model"] = first
    return one


def accumulate(acc, usage):
    """Fold one call's usage (from parse_usage) into a running accumulator (from empty()). Returns acc.

    Sums token classes + cost, increments the call count, and pins the first non-null model seen (so a
    later empty/failed call cannot blank out the model already recorded)."""
    for k in _TOKEN_FIELDS:
        v = usage.get(k, 0) or 0
        acc[k] = acc.get(k, 0) + (int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0)
    c = usage.get("cost_usd", 0.0) or 0.0
    acc["cost_usd"] = round(acc.get("cost_usd", 0.0) + (float(c) if isinstance(c, (int, float)) else 0.0), 6)
    acc["calls"] = acc.get("calls", 0) + 1
    if not acc.get("model") and usage.get("model"):
        acc["model"] = usage["model"]
    return acc


def total_tokens(acc):
    """All token classes summed — convenience for a headline number (report classes separately for claims)."""
    return sum(int(acc.get(k, 0) or 0) for k in _TOKEN_FIELDS)


def summary_line(acc):
    """A one-line human summary for loop output / PR evidence."""
    return (f"{acc.get('calls', 0)} call(s) · in={acc.get('input_tokens', 0)} "
            f"out={acc.get('output_tokens', 0)} cache_read={acc.get('cache_read_input_tokens', 0)} "
            f"cache_create={acc.get('cache_creation_input_tokens', 0)} · ${acc.get('cost_usd', 0.0):.4f}"
            + (f" · {acc['model']}" if acc.get("model") else ""))


if __name__ == "__main__":
    import sys
    acc = empty()
    for chunk in sys.stdin.read().split("\n\n"):
        if chunk.strip():
            acc = accumulate(acc, parse_usage(chunk))
    print(summary_line(acc))
