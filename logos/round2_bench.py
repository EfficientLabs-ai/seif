#!/usr/bin/env python3
"""Round 2a — the model-routing FRONTIER + an escalation router.

E3 showed routing to a cheaper model is ~−86% cheaper at EQUAL resolve-rate — but only on easy bugs where
every model succeeds. This finds where that breaks: a difficulty-graded set (easy + genuinely-hard
algorithmic bugs with multi-assertion tests) measured per-model, plus an ESCALATION router (haiku → sonnet
→ opus: try cheap, escalate on a failing test) — the production pattern. The honest metric is
cost-per-RESOLVED. Real `claude -p`; retry-on-empty; full env; only --model varies.
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
OPUS, SONNET, HAIKU = "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"
LADDER = [HAIKU, SONNET, OPUS]          # escalation order: cheapest → strongest

# --- task set: (id, difficulty, task, test_module, source_path, source_body, test_body) ----------------
def _t(tid, diff, task, mod, src, srcbody, testbody):
    return dict(id=tid, diff=diff, task=task, mod=mod, src=src, srcbody=srcbody, testbody=testbody)

TASKS = [
    # EASY — single-file, obvious (every model should pass)
    _t("easy_add", "easy", "Fix pkg/ops.py so add(a, b) returns the sum. Do not edit tests.",
       "tests.test_ops", "pkg/ops.py", "def add(a, b):\n    return a - b\n",
       "import unittest\nfrom pkg.ops import add\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(add(2,3),5); self.assertEqual(add(10,5),15)\n"),
    _t("easy_clamp", "easy", "Fix pkg/nums.py so clamp(x, lo, hi) clamps x into [lo, hi]. Do not edit tests.",
       "tests.test_nums", "pkg/nums.py", "def clamp(x, lo, hi):\n    return x\n",
       "import unittest\nfrom pkg.nums import clamp\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(clamp(15,0,10),10); self.assertEqual(clamp(-3,0,10),0); self.assertEqual(clamp(5,0,10),5)\n"),
    # HARD — algorithmic, multi-assertion tests; the buggy version passes a naive subset only
    _t("hard_roman", "hard", "Fix pkg/roman.py so to_roman(n) produces correct Roman numerals (subtractive notation). Do not edit tests.",
       "tests.test_roman", "pkg/roman.py",
       "def to_roman(n):\n    vals=[(1000,'M'),(500,'D'),(100,'C'),(50,'L'),(10,'X'),(5,'V'),(1,'I')]\n    out=''\n    for v,s in vals:\n        while n>=v:\n            out+=s; n-=v\n    return out\n",
       "import unittest\nfrom pkg.roman import to_roman\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(to_roman(4),'IV'); self.assertEqual(to_roman(9),'IX')\n        self.assertEqual(to_roman(40),'XL'); self.assertEqual(to_roman(90),'XC')\n        self.assertEqual(to_roman(58),'LVIII'); self.assertEqual(to_roman(1994),'MCMXCIV')\n"),
    _t("hard_merge", "hard", "Fix pkg/intervals.py so merge(intervals) merges all overlapping/adjacent intervals. Do not edit tests.",
       "tests.test_intervals", "pkg/intervals.py", "def merge(intervals):\n    return intervals\n",
       "import unittest\nfrom pkg.intervals import merge\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(merge([[1,3],[2,6],[8,10],[15,18]]),[[1,6],[8,10],[15,18]])\n        self.assertEqual(merge([[1,4],[4,5]]),[[1,5]])\n        self.assertEqual(merge([[1,4],[2,3]]),[[1,4]])\n"),
    _t("hard_balanced", "hard", "Fix pkg/brackets.py so is_balanced(s) checks correctly nested/typed brackets. Do not edit tests.",
       "tests.test_brackets", "pkg/brackets.py", "def is_balanced(s):\n    return s.count('(')==s.count(')')\n",
       "import unittest\nfrom pkg.brackets import is_balanced\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertTrue(is_balanced('([])')); self.assertFalse(is_balanced('([)]'))\n        self.assertTrue(is_balanced('{[()]}')); self.assertFalse(is_balanced('(((')); self.assertTrue(is_balanced(''))\n"),
]


def build_fixture(dst):
    os.makedirs(os.path.join(dst, "pkg"), exist_ok=True)
    os.makedirs(os.path.join(dst, "tests"), exist_ok=True)
    open(os.path.join(dst, "pkg", "__init__.py"), "w").close()
    open(os.path.join(dst, "tests", "__init__.py"), "w").close()
    open(os.path.join(dst, ".gitignore"), "w").write("__pycache__/\n*.pyc\n")
    for t in TASKS:
        open(os.path.join(dst, t["src"]), "w").write(t["srcbody"])
        open(os.path.join(dst, t["mod"].replace(".", "/") + ".py"), "w").write(t["testbody"])
    g = lambda *a: subprocess.run(["git", "-C", dst, "-c", "user.name=b", "-c", "user.email=b@b", *a],
                                  check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", dst], check=True)
    g("add", "-A"); g("commit", "-qm", "fixture")
    return dst


def prompt_for(task):
    return (f"You are making a focused change in this repository (cwd).\n\nTASK:\n{task}\n\n"
            "Edit the SOURCE to accomplish it and make the project's tests pass. Do NOT edit tests. "
            "Make the change and stop.")


def one_call(repo, task, mod, model, timeout=600):
    cmd_test = f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m unittest {mod}"
    for _ in range(3):
        wt = H.checkpoint(repo, "HEAD")
        try:
            argv = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                    "--model", model, prompt_for(task)]
            p = subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=timeout)
            u = UM.parse_usage(p.stdout)
            if UM.total_tokens(u) == 0:
                continue
            res = H.run_tests(wt, cmd_test, timeout=120)
            return {**u, "resolved": res.get("outcome") == "pass"}
        finally:
            H.discard(repo, wt)
    return {**UM.parse_usage(""), "resolved": False}


def escalate(repo, t):
    """Try cheapest → escalate on failing test. Cumulative cost; record which model finally resolved."""
    total = UM.empty()
    resolver, attempts = None, []
    for model in LADDER:
        r = one_call(repo, t["task"], t["mod"], model)
        UM.accumulate(total, r)
        attempts.append({"model": model, "resolved": r["resolved"], "cost": r["cost_usd"]})
        if r["resolved"]:
            resolver = model
            break
    return {"resolved": resolver is not None, "resolver": resolver,
            "cost_usd": total["cost_usd"], "attempts": attempts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--out", default="/tmp/round2_report.json")
    a = ap.parse_args()
    repo = build_fixture(tempfile.mkdtemp(prefix="r2-"))
    matrix, esc = [], []
    try:
        # frontier matrix: task × model
        for t in TASKS:
            for s in range(a.seeds):
                for model in (OPUS, SONNET, HAIKU):
                    r = one_call(repo, t["task"], t["mod"], model)
                    matrix.append({"task": t["id"], "diff": t["diff"], "seed": s, "model": model,
                                   "resolved": r["resolved"], "cost_usd": r["cost_usd"]})
                    print(f"[matrix {t['id']:14s} {t['diff']:4s} s{s}] {model:30s} ok={r['resolved']} ${r['cost_usd']:.4f}")
        # escalation router (one pass per task)
        for t in TASKS:
            e = escalate(repo, t)
            e["task"], e["diff"] = t["id"], t["diff"]
            esc.append(e)
            print(f"[escalate {t['id']:14s} {t['diff']:4s}] resolved={e['resolved']} by={e['resolver']} "
                  f"${e['cost_usd']:.4f} ({'→'.join(x['model'].split('-')[1] for x in e['attempts'])})")

        # summaries
        def per(model, diff=None):
            rs = [m for m in matrix if m["model"] == model and (diff is None or m["diff"] == diff)]
            res = sum(1 for m in rs if m["resolved"]); cost = sum(m["cost_usd"] for m in rs)
            return {"runs": len(rs), "resolved": res, "resolve_rate": round(res/len(rs), 3) if rs else None,
                    "cost_per_resolved": round(cost/res, 6) if res else None,
                    "total_cost": round(cost, 6)}
        frontier = {model: {"all": per(model), "easy": per(model, "easy"), "hard": per(model, "hard")}
                    for model in (OPUS, SONNET, HAIKU)}
        n = len(esc); eres = sum(1 for e in esc if e["resolved"]); ecost = sum(e["cost_usd"] for e in esc)
        router = {"tasks": n, "resolved": eres, "resolve_rate": round(eres/n, 3) if n else None,
                  "total_cost": round(ecost, 6), "cost_per_resolved": round(ecost/eres, 6) if eres else None,
                  "resolver_mix": dict(collections.Counter(e["resolver"] for e in esc))}
        report = {"matrix": matrix, "escalation": esc, "frontier": frontier, "router": router}
        json.dump(report, open(a.out, "w"), indent=2)
        print("\n=== FRONTIER (resolve-rate · $/resolved, by difficulty) ===")
        for model in (OPUS, SONNET, HAIKU):
            f = frontier[model]
            print(f"{model:30s} all {f['all']['resolve_rate']} (${f['all']['cost_per_resolved']})  "
                  f"easy {f['easy']['resolve_rate']}  hard {f['hard']['resolve_rate']} (${f['hard']['cost_per_resolved']})")
        print(f"\n=== ESCALATION ROUTER (haiku→sonnet→opus) ===")
        print(f"resolved {router['resolved']}/{router['tasks']} · $/resolved={router['cost_per_resolved']} · "
              f"total=${router['total_cost']} · resolver mix={router['resolver_mix']}")
        print(f"  vs always-opus  $/resolved={frontier[OPUS]['all']['cost_per_resolved']} "
              f"(resolve {frontier[OPUS]['all']['resolve_rate']})")
        print(f"  vs always-haiku $/resolved={frontier[HAIKU]['all']['cost_per_resolved']} "
              f"(resolve {frontier[HAIKU]['all']['resolve_rate']})")
        print(f"\nreport -> {a.out}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
