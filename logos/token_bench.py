#!/usr/bin/env python3
"""token_bench — a FAST, controlled token-economics A/B for the SEIF loop.

Purpose: produce a MEASURED token/cost number for the loop instead of an asserted one. Deliberately NOT
SWE-bench (which spends hours cloning repos + running heavy suites): a small generated fixture with
second-level tests, so a real run is minutes. Every arm goes through the SAME instrumented chokepoint
(`seif_run._claude_edit` → `usage_meter`), so the token numbers are directly comparable.

Phase 1 (baseline): `oneshot` (single edit, one test run) vs `loop` (the gated SEIF loop, budget>1).
Phase 2 (savings, later): `loop` vs `loop+delta` once delta_context is wired — the difference is the
architecture's token savings, with the Phase-1 baseline as the control.

Honest scope: a capable model self-scopes its reading, so delta savings show up mainly on cold-start
RETRIES and in prompt size — this bench is built to expose exactly that, not to flatter it.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_harness as H   # noqa: E402
import seif_run as SR         # noqa: E402
import usage_meter as UM      # noqa: E402

# ---- fixture: a small multi-module package with localized bugs + failing unit tests --------------------
# An import chain (api -> ops -> core) plus filler modules, so a blast-radius graph is meaningful in
# Phase 2. Each task fixes ONE localized bug; the suite for a task runs in well under a second.
_MODULES = {
    "pkg/__init__.py": "",
    "pkg/core.py": "def inc(x):\n    return x + 1\n",
    "pkg/ops.py": "from pkg.core import inc\n\n\ndef add(a, b):\n    return a - b   # BUG: should be a + b\n",
    "pkg/api.py": "from pkg.ops import add\n\n\ndef total(xs):\n    t = 0\n    for x in xs:\n        t = add(t, x)\n    return t\n",
    "pkg/text.py": "def shout(s):\n    return s.lower()   # BUG: should be s.upper()\n",
    "pkg/nums.py": "def clamp(x, lo, hi):\n    return x   # BUG: should clamp into [lo, hi]\n",
}
# filler modules to give the repo some size (so 'read everything' is non-trivial in Phase 2)
for _i in range(8):
    _MODULES[f"pkg/util{_i}.py"] = f"def helper{_i}(x):\n    return x * {_i + 1}\n"

# (task_id, human task, test module, test body) — unittest TestCase; each fails until the bug is fixed.
_TASKS = [
    ("fix_add", "Fix the bug in pkg/ops.py so add(a, b) returns the sum. Do not edit tests.",
     "tests.test_ops",
     "import unittest\nfrom pkg.ops import add\n\n\nclass T(unittest.TestCase):\n"
     "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n        self.assertEqual(add(10, 5), 15)\n"),
    ("fix_shout", "Fix the bug in pkg/text.py so shout(s) upper-cases the string. Do not edit tests.",
     "tests.test_text",
     "import unittest\nfrom pkg.text import shout\n\n\nclass T(unittest.TestCase):\n"
     "    def test_shout(self):\n        self.assertEqual(shout('abc'), 'ABC')\n"),
    ("fix_clamp", "Fix the bug in pkg/nums.py so clamp(x, lo, hi) clamps x into [lo, hi]. Do not edit tests.",
     "tests.test_nums",
     "import unittest\nfrom pkg.nums import clamp\n\n\nclass T(unittest.TestCase):\n"
     "    def test_clamp(self):\n        self.assertEqual(clamp(15, 0, 10), 10)\n"
     "        self.assertEqual(clamp(-3, 0, 10), 0)\n        self.assertEqual(clamp(5, 0, 10), 5)\n"),
]


def build_fixture(dst):
    """Materialize the fixture as a committed git repo at `dst`. Returns the repo path."""
    os.makedirs(dst, exist_ok=True)
    for rel, body in _MODULES.items():
        p = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(body)
    os.makedirs(os.path.join(dst, "tests"), exist_ok=True)
    open(os.path.join(dst, "tests", "__init__.py"), "w").write("")
    # As any real Python repo has: ignore bytecode caches. Without this, running the suite writes
    # tests/__pycache__/*.pyc, `git add -A` stages them, and the integrity guard flags them as
    # protected test-path edits — spuriously failing every loop-arm fix and corrupting the measurement.
    open(os.path.join(dst, ".gitignore"), "w").write("__pycache__/\n*.pyc\n")
    for _id, _task, mod, tbody in _TASKS:
        rel = mod.replace(".", "/") + ".py"          # 'tests.test_ops' -> 'tests/test_ops.py'
        open(os.path.join(dst, rel), "w").write(tbody)
    g = lambda *a: subprocess.run(["git", "-C", dst, "-c", "user.name=bench", "-c", "user.email=b@b", *a],
                                  check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", dst], check=True)
    g("add", "-A"); g("commit", "-qm", "fixture")
    return dst


def run_oneshot(repo, task, test_cmd, timeout):
    """Naive baseline: a single metered edit + one test run. No retries, no gate. Uses the SAME
    instrumented chokepoint as the loop so token numbers are comparable."""
    wt = H.checkpoint(repo, "HEAD")
    try:
        _rc, usage = SR._claude_edit(wt, task, "", True, timeout)
        res = H.run_tests(wt, test_cmd, timeout=timeout)
        return {"resolved": res.get("outcome") == "pass", "usage": usage, "attempts": 1}
    finally:
        H.discard(repo, wt)


def run_loop(repo, task, test_cmd, budget, timeout):
    """The gated SEIF loop (no PR). Already meters every attempt and returns summed usage + accepted."""
    r = SR.seif_run(repo, task, test_cmd, budget=budget, base="HEAD", make_pr=False, timeout=timeout)
    usage = r.get("usage") or UM.empty()
    return {"resolved": bool(r.get("accepted")), "usage": usage, "attempts": usage.get("calls", 0)}


_TOKEN_FIELDS = ("input_tokens", "output_tokens",
                 "cache_creation_input_tokens", "cache_read_input_tokens")


def _totals(rows):
    """Aggregate arm rows into totals + the honest denominator (cost per RESOLVED task).

    Each row's usage is summed field-by-field; `calls` comes from the loop's own accumulator (or counts
    as 1 for the single-call oneshot arm), so the per-arm model-call count stays real."""
    acc = UM.empty()
    resolved = 0
    for r in rows:
        u = r["usage"]
        for k in _TOKEN_FIELDS:
            acc[k] += int(u.get(k, 0) or 0)
        acc["cost_usd"] = round(acc["cost_usd"] + float(u.get("cost_usd", 0.0) or 0.0), 6)
        acc["calls"] += int(u.get("calls", 1) or 1)
        if not acc.get("model") and u.get("model"):
            acc["model"] = u["model"]
        resolved += 1 if r["resolved"] else 0
    acc["tasks"] = len(rows)
    acc["resolved"] = resolved
    acc["total_tokens"] = UM.total_tokens(acc)
    acc["cost_per_resolved"] = round(acc["cost_usd"] / resolved, 6) if resolved else None
    acc["tokens_per_resolved"] = round(acc["total_tokens"] / resolved, 1) if resolved else None
    return acc


def run_bench(repo, tasks, budget=3, timeout=180):
    """Run both baseline arms over every task. Returns {arm: {rows, totals}}."""
    arms = {"oneshot": [], "loop": []}
    for tid, task, mod, _tb in tasks:
        # PYTHONDONTWRITEBYTECODE: belt-and-suspenders with the fixture .gitignore — no .pyc to stage at all.
        cmd = f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m unittest {mod}"
        t0 = time.time()
        one = run_oneshot(repo, task, cmd, timeout)
        two = run_loop(repo, task, cmd, budget, timeout)
        one["task"], two["task"] = tid, tid
        arms["oneshot"].append(one)
        arms["loop"].append(two)
        print(f"[bench] {tid}: oneshot resolved={one['resolved']} ${one['usage'].get('cost_usd',0):.4f} "
              f"| loop resolved={two['resolved']} calls={two['attempts']} ${two['usage'].get('cost_usd',0):.4f} "
              f"({time.time()-t0:.0f}s)")
    return {arm: {"rows": rows, "totals": _totals(rows)} for arm, rows in arms.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--tasks", type=int, default=len(_TASKS), help="how many of the fixture tasks to run")
    ap.add_argument("--out", default="/tmp/token_bench_report.json")
    a = ap.parse_args()
    repo = build_fixture(tempfile.mkdtemp(prefix="tokbench-"))
    try:
        report = run_bench(repo, _TASKS[:a.tasks], budget=a.budget, timeout=a.timeout)
        for arm, d in report.items():
            t = d["totals"]
            print(f"\n=== {arm} ===  resolved {t['resolved']}/{t['tasks']}  "
                  f"total_tokens={t['total_tokens']}  cost=${t['cost_usd']:.4f}  "
                  f"tokens/resolved={t['tokens_per_resolved']}  $/resolved={t['cost_per_resolved']}")
        json.dump(report, open(a.out, "w"), indent=2)
        print(f"\nreport -> {a.out}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
