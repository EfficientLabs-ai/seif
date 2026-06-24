#!/usr/bin/env python3
"""SEIF Context Bill of Materials (CBOM) — a STATIC inventory of what every Claude Code call silently loads.

The reframe (2026-06-24): the dominant token lever is LOAD architecture — what enters every call before the
task does. `loadarch_bench.py` measures the *aggregate* env tax by SUBTRACTION via live `claude -p` arms
(full−noUser = user-config cost, etc.). This module is the complementary STATIC decomposition: it itemizes
the loaded config surface — CLAUDE.md files, skills, plugins, hooks, MCP servers — and attaches an
approximate per-item token size, so the ~17K user-config tax becomes a per-item breakdown the founder can
read line by line and decide what to gate.

A CBOM is a plain JSON dict:
  {"version": "0.1", "generated_at": "<iso8601>", "items": [
      {"kind": "user_config", "name": "~/.claude/CLAUDE.md", "path": "...", "tokens": 4200, "bytes": 16800},
      {"kind": "skill",       "name": "graphify",            "tokens": 180},
      ... ],
   "session": {...optional raw hook payload...}}

`kind` is one of CATEGORIES (everything else folds into "other"). Token sizes are APPROXIMATE — a pure
~4-chars-per-token heuristic, never a live tokenizer call — because the point is relative attribution
(which item costs what), not billing. Pure, dependency-free, NO-THROW: a missing file or malformed CBOM
degrades to zero/empty rather than raising, so this can run from a session-start hook without ever breaking
a session.
"""
import json
import os

VERSION = "0.1"

# The categories `summarize` reports. A CBOM item whose `kind` is not one of these folds into "other".
# user_config = CLAUDE.md + skills + plugins + hooks (the user-config tax that --setting-sources project drops);
# mcp = MCP server tool schemas; base = the fixed CLI/system scaffold (always present, not user-gateable).
CATEGORIES = ("user_config", "skill", "plugin", "hook", "mcp", "base")

# How summarize() rolls per-item `kind`s up into the founder-facing report buckets. skill/plugin/hook all
# count toward `user_config` AND get their own line, so the founder sees both the total tax and its parts.
_CONFIG_KINDS = ("user_config", "skill", "plugin", "hook")

_CHARS_PER_TOKEN = 4  # coarse GPT/Claude-family rule of thumb; relative attribution, not a billing number.


def estimate_tokens(text):
    """Approximate token count for a string or bytes, ~4 chars/token, rounded up. No-throw: None/other → 0.

    This is deliberately a heuristic, never a tokenizer — the CBOM compares item sizes to each other, so a
    consistent cheap estimate beats an exact-but-fragile one. Whitespace counts (it costs context too)."""
    if text is None:
        return 0
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — never raise out of a hook-callable primitive
            return 0
    if not isinstance(text, str):
        return 0
    n = len(text)
    return (n + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN  # ceil division, no float


def estimate_file_tokens(path):
    """(tokens, bytes) for a file's content via estimate_tokens. Missing/unreadable file → (0, 0)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except Exception:  # noqa: BLE001 — absent/unreadable file degrades to zero, never raises
        return 0, 0
    return estimate_tokens(data), len(data)


def make_item(kind, name, *, tokens=0, path=None, bytes_=None, **extra):
    """Build one normalized CBOM item. `kind` outside CATEGORIES is preserved verbatim (summarize folds it
    into 'other'); tokens is coerced to a non-negative int so a bad value can never poison a sum."""
    try:
        tok = int(tokens)
    except Exception:  # noqa: BLE001
        tok = 0
    item = {"kind": str(kind), "name": str(name), "tokens": max(tok, 0)}
    if path is not None:
        item["path"] = str(path)
    if bytes_ is not None:
        try:
            item["bytes"] = max(int(bytes_), 0)
        except Exception:  # noqa: BLE001
            pass
    item.update(extra)
    return item


def make_cbom(items, *, generated_at=None, session=None, version=VERSION):
    """Wrap a list of items into a CBOM dict. Non-list `items` → []; the structure is always well-formed so
    parse()/summarize() never have to special-case it."""
    return {"version": version,
            "generated_at": generated_at,
            "items": list(items) if isinstance(items, (list, tuple)) else [],
            "session": session if isinstance(session, dict) else {}}


def parse(path):
    """Load a CBOM JSON file from `path` → a well-formed CBOM dict. NO-THROW: a missing file, non-JSON, or a
    JSON value that isn't an object degrades to an empty CBOM ({version, items:[], ...}) rather than raising.

    Always returns a dict with an `items` list (coerced if the file carried a non-list), so downstream
    summarize() can iterate without guards."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception:  # noqa: BLE001 — absent/partial/non-JSON → empty CBOM, never a crash
        return make_cbom([])
    if not isinstance(obj, dict):
        return make_cbom([])
    items = obj.get("items")
    obj["items"] = items if isinstance(items, list) else []
    obj.setdefault("version", VERSION)
    return obj


def summarize(cbom):
    """Roll a CBOM up into per-category token totals: {user_config, skills, hooks, mcp, base, total, ...}.

    Buckets (so the founder reads both the headline tax and its parts):
      • user_config — sum of skill+plugin+hook+user_config items (the tax `--setting-sources project` drops)
      • skills / hooks / mcp / base — per-kind subtotals
      • other        — any item whose kind isn't in CATEGORIES (so nothing is silently dropped from `total`)
      • total        — every item's tokens (== user_config + mcp + base + plugins-not-already + other),
                       computed as a straight sum so it always equals the CBOM's real footprint
      • count        — number of items
    Each value is an int. Malformed items (missing/non-int tokens) contribute 0, never raise."""
    items = cbom.get("items") if isinstance(cbom, dict) else None
    if not isinstance(items, list):
        items = []

    per_kind = {}
    total = 0
    count = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind", "other"))
        try:
            tok = int(it.get("tokens", 0))
        except Exception:  # noqa: BLE001
            tok = 0
        if tok < 0:
            tok = 0
        per_kind[kind] = per_kind.get(kind, 0) + tok
        total += tok
        count += 1

    in_categories = sum(v for k, v in per_kind.items() if k in CATEGORIES)
    other = total - in_categories
    return {
        # the founder-facing tax = CLAUDE.md + skills + plugins + hooks
        "user_config": sum(per_kind.get(k, 0) for k in _CONFIG_KINDS),
        # per-kind lines (plural keys for the human-facing report)
        "skills": per_kind.get("skill", 0),
        "plugins": per_kind.get("plugin", 0),
        "hooks": per_kind.get("hook", 0),
        "mcp": per_kind.get("mcp", 0),
        "base": per_kind.get("base", 0),
        "other": other,
        "total": total,
        "count": count,
    }


def summary_line(cbom):
    """One-line human summary for hook stderr / PR evidence. No-throw on any input (non-dict → defaults),
    so it shares summarize()'s degrade-don't-raise contract end to end."""
    s = summarize(cbom)
    version = cbom.get("version", VERSION) if isinstance(cbom, dict) else VERSION
    return (f"CBOM {version}: {s['count']} item(s) · "
            f"user_config={s['user_config']} (skills={s['skills']} plugins={s['plugins']} hooks={s['hooks']}) · "
            f"mcp={s['mcp']} base={s['base']} other={s['other']} · total≈{s['total']} tok")


def _selftest():
    cb = make_cbom([
        make_item("user_config", "~/.claude/CLAUDE.md", tokens=1000),
        make_item("skill", "graphify", tokens=200),
        make_item("skill", "deep-research", tokens=300),
        make_item("plugin", "superpowers", tokens=150),
        make_item("hook", "session-boot", tokens=50),
        make_item("mcp", "Notion", tokens=4000),
        make_item("base", "system-prompt", tokens=2000),
        make_item("weird", "uncategorized", tokens=7),
    ])
    s = summarize(cb)
    assert s["count"] == 8, s
    assert s["skills"] == 500 and s["plugins"] == 150 and s["hooks"] == 50, s
    assert s["user_config"] == 1000 + 500 + 150 + 50, s  # CLAUDE.md + skills + plugins + hooks
    assert s["mcp"] == 4000 and s["base"] == 2000, s
    assert s["other"] == 7, s  # unknown kind is surfaced, never dropped
    assert s["total"] == 1000 + 500 + 150 + 50 + 4000 + 2000 + 7, s
    # total must always equal the straight item sum (no double counting / no leakage)
    assert s["total"] == sum(i["tokens"] for i in cb["items"]), s

    # token heuristic: ceil(chars/4); no-throw on junk
    assert estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2
    assert estimate_tokens("") == 0 and estimate_tokens(None) == 0 and estimate_tokens(123) == 0
    assert estimate_tokens(b"abcdefgh") == 2

    # parse() is no-throw on a missing path -> empty, well-formed CBOM
    empty = parse("/nonexistent/path/cbom.json")
    assert empty["items"] == [] and summarize(empty)["total"] == 0

    # summarize() tolerates malformed items without raising
    bad = summarize({"items": [None, {"kind": "skill"}, {"kind": "skill", "tokens": "x"},
                                {"kind": "skill", "tokens": -5}, {"kind": "skill", "tokens": 9}]})
    assert bad["skills"] == 9 and bad["count"] == 4, bad  # None skipped; bad/neg tokens -> 0

    # summary_line is no-throw on non-dict input too (shares summarize's contract)
    for junk in (None, [], "x", 7):
        assert isinstance(summary_line(junk), str)
    print("cbom selftest PASS — static per-item token attribution; user_config = CLAUDE.md+skills+plugins+hooks; "
          "total always equals the item sum; parse/summarize are no-throw on missing files & malformed items")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    elif len(sys.argv) > 1:
        print(summary_line(parse(sys.argv[1])))
    else:
        print("usage: cbom.py --selftest | cbom.py <path-to-cbom.json>")
