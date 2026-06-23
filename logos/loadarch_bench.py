#!/usr/bin/env python3
"""Round 3 — the LOADING ABLATION + Context Bill of Materials (CBOM).

The reframe (2026-06-24): the dominant token lever is LOAD architecture — what enters every call — not
graph retrieval. This decomposes the per-call environment tax by SOURCE, holding the task + model constant
and varying only what the `claude` CLI loads:

  full    : default environment (user CLAUDE.md + skills + hooks + MCP + tools)
  noMCP   : --strict-mcp-config            (drops MCP servers)
  noUser  : --setting-sources project      (drops user CLAUDE.md / skills / hooks)
  bare    : --bare                         (minimal mode: skip hooks/LSP/plugins/skills/MCP/CLAUDE.md)

Decomposition (CBOM by subtraction, on model-independent fresh-input tokens):
  full − noMCP  = MCP schema cost ·  full − noUser = user CLAUDE.md/skills/hooks cost ·  full − bare = total tax

Every call records model_requested vs model_actual (item 3: the silent-downgrade guard) and the four token
classes (item 1: CBOM). Real `claude -p`; retry-on-empty; --model pins opus in every arm.
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_harness as H  # noqa: E402
import usage_meter as UM     # noqa: E402

CLAUDE = "/home/neo/.local/bin/claude"
MODEL = "claude-opus-4-8"

# Arm = (id, extra flags). --model pins the model in every arm so fresh-input deltas isolate LOAD, not model.
ARMS = [
    ("full",   []),
    ("noMCP",  ["--strict-mcp-config"]),
    ("noUser", ["--setting-sources", "project"]),
    ("bare",   ["--bare"]),
]

# Small single-file bug tasks — the "work" tokens are ~constant, so the per-arm fresh-input delta is the env.
TASKS = [
    ("add", "Fix pkg/ops.py so add(a, b) returns the sum. Do not edit tests.", "tests.test_ops",
     "pkg/ops.py", "def add(a, b):\n    return a - b\n",
     "import unittest\nfrom pkg.ops import add\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(add(2,3),5); self.assertEqual(add(10,5),15)\n"),
    ("clamp", "Fix pkg/nums.py so clamp(x, lo, hi) clamps x into [lo, hi]. Do not edit tests.", "tests.test_nums",
     "pkg/nums.py", "def clamp(x, lo, hi):\n    return x\n",
     "import unittest\nfrom pkg.nums import clamp\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(clamp(15,0,10),10); self.assertEqual(clamp(-3,0,10),0)\n"),
]


def build_fixture(dst):
    os.makedirs(os.path.join(dst, "pkg"), exist_ok=True)
    os.makedirs(os.path.join(dst, "tests"), exist_ok=True)
    open(os.path.join(dst, "pkg", "__init__.py"), "w").close()
    open(os.path.join(dst, "tests", "__init__.py"), "w").close()
    open(os.path.join(dst, ".gitignore"), "w").write("__pycache__/\n*.pyc\n")
    for _id, _t, _m, src, srcbody, testbody in TASKS:
        open(os.path.join(dst, src), "w").write(srcbody)
        open(os.path.join(dst, _m.replace(".", "/") + ".py"), "w").write(testbody)
    g = lambda *a: subprocess.run(["git", "-C", dst, "-c", "user.name=b", "-c", "user.email=b@b", *a],
                                  check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", dst], check=True)
    g("add", "-A"); g("commit", "-qm", "fixture")
    return dst


def prompt_for(task):
    return (f"You are making a focused change in this repository (cwd).\n\nTASK:\n{task}\n\n"
            "Edit the SOURCE to accomplish it and make the project's tests pass. Do NOT edit tests. "
            "Make the change and stop.")


def env_decomposition(per_arm, arms=ARMS):
    """Decompose the env tax: a source's fresh-input cost = full − (arm with that source stripped).
    Returns None (NOT a bogus full−0) for any source whose arm failed — e.g. a `--bare` arm that returned
    empty must never masquerade as a 'zero-token tax'. Also lists which arms produced no usable call."""
    f = per_arm.get("full", {}).get("fresh_input")

    def d(arm):
        v = per_arm.get(arm, {}).get("fresh_input")
        return round(f - v, 2) if (f is not None and v is not None) else None
    return {"total_env_tax_fresh_input": d("bare"), "mcp_fresh_input": d("noMCP"),
            "user_config_fresh_input": d("noUser"),
            "failed_arms": [a for a, _ in arms if per_arm.get(a, {}).get("fresh_input") is None]}


def cbom(repo, task, mod, flags, timeout=600):
    """One metered call under a given LOAD profile. Returns a Context Bill of Materials row (item 1) with
    model_requested vs model_actual (item 3) + the four token classes; retry-on-empty (max 3)."""
    cmd_test = f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m unittest {mod}"
    for _ in range(3):
        wt = H.checkpoint(repo, "HEAD")
        try:
            argv = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                    "--model", MODEL, *flags, prompt_for(task)]
            p = subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=timeout)
            u = UM.parse_usage(p.stdout)
            if UM.total_tokens(u) == 0:
                continue
            res = H.run_tests(wt, cmd_test, timeout=120)
            return {"fresh_input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                    "cache_read": u.get("cache_read_input_tokens", 0),
                    "cache_create": u.get("cache_creation_input_tokens", 0),
                    "cost_usd": u.get("cost_usd", 0.0), "resolved": res.get("outcome") == "pass",
                    "model_requested": MODEL, "model_actual": u.get("model"),
                    "model_mismatch": (u.get("model") or "").split("[")[0] != MODEL}
        finally:
            H.discard(repo, wt)
    return {"fresh_input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "cost_usd": 0.0,
            "resolved": False, "model_requested": MODEL, "model_actual": None, "model_mismatch": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--out", default="/tmp/round3_report.json")
    a = ap.parse_args()
    repo = build_fixture(tempfile.mkdtemp(prefix="r3-"))
    rows = []
    try:
        for tid, task, mod, _s, _sb, _tb in TASKS:
            for s in range(a.seeds):
                for arm, flags in ARMS:
                    r = cbom(repo, task, mod, flags)
                    r.update({"task": tid, "seed": s, "arm": arm})
                    rows.append(r)
                    print(f"[r3 {tid:6s} s{s} {arm:7s}] ok={r['resolved']} fresh_in={r['fresh_input']:6d} "
                          f"cache_read={r['cache_read']:7d} ${r['cost_usd']:.4f} model={r['model_actual']}"
                          + ("  *MISMATCH*" if r["model_mismatch"] else ""))
        # per-arm means (fresh input is the model-independent decomposition signal)
        def mean(arm, key):
            vs = [r[key] for r in rows if r["arm"] == arm and r["fresh_input"] > 0]
            return round(sum(vs) / len(vs), 2) if vs else None
        per_arm = {arm: {"fresh_input": mean(arm, "fresh_input"), "cache_read": mean(arm, "cache_read"),
                         "cost_usd": mean(arm, "cost_usd"),
                         "resolve_rate": round(sum(1 for r in rows if r["arm"] == arm and r["resolved"])
                                               / max(1, sum(1 for r in rows if r["arm"] == arm)), 3),
                         "models": sorted({r["model_actual"] for r in rows if r["arm"] == arm and r["model_actual"]})}
                   for arm, _ in ARMS}
        decomp = env_decomposition(per_arm)
        mismatches = sum(1 for r in rows if r["model_mismatch"])
        report = {"rows": rows, "per_arm": per_arm, "decomposition": decomp, "model_mismatches": mismatches}
        json.dump(report, open(a.out, "w"), indent=2)
        print("\n=== CBOM per-arm (mean fresh-input · cache_read · $ · resolve · models) ===")
        for arm, _ in ARMS:
            p = per_arm[arm]
            print(f"{arm:8s} fresh_in={p['fresh_input']}  cache_read={p['cache_read']}  ${p['cost_usd']}  "
                  f"resolve={p['resolve_rate']}  models={p['models']}")
        print("\n=== ENV-TAX DECOMPOSITION (fresh input, model-independent) ===")
        print(f"  total tax (full−bare)     = {decomp['total_env_tax_fresh_input']} tokens/call")
        print(f"  user CLAUDE.md/skills/hooks (full−noUser) = {decomp['user_config_fresh_input']}")
        print(f"  MCP schemas (full−noMCP)  = {decomp['mcp_fresh_input']}")
        print(f"  model mismatches (silent downgrades): {mismatches}/{len(rows)}")
        print(f"\nreport -> {a.out}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
