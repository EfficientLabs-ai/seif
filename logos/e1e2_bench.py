#!/usr/bin/env python3
"""E1 + E2: the two experiments that make the token-economics claims defensible.

E1 (cost lever): SAME model (opus, robustly pinned via --settings JSON) full vs lean per-call environment,
   across tasks x seeds, with FOUR token classes reported separately (so a 'saving' can't be a cheap-cache
   artifact) + a conservative cost-excluding-cache-read figure (the real-money floor).
E2 (graph go/no-go): on MULTI-HOP bugs (failing test far from the root cause), does telling the model the
   forward-dependency closure of the failing test ('look only at these files') cut fresh-input tokens at
   equal resolve-rate vs letting it navigate freely? This is the decisive test of whether ANY graph-scoping
   saves tokens — the right experiment, since blast-radius (reverse) was the wrong direction.

All arms: opus pinned, retry-on-empty (zero-token envelope = infra hiccup -> retry), real `claude -p`.
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
import project_harness as H   # noqa: E402
import usage_meter as UM      # noqa: E402

CLAUDE = "/home/neo/.local/bin/claude"
PIN = ["--settings", '{"model":"claude-opus-4-8"}', "--model", "claude-opus-4-8"]
LEAN = ["--strict-mcp-config", "--setting-sources", "project"]

# ---- E1 fixture: single-file localized bugs (root cause == where the failing test points) -------------
E1_FILES = {
    "pkg/__init__.py": "",
    "pkg/ops.py": "def add(a, b):\n    return a - b   # BUG: should be a + b\n",
    "pkg/text.py": "def shout(s):\n    return s.lower()   # BUG: should be s.upper()\n",
    "pkg/nums.py": "def clamp(x, lo, hi):\n    return x   # BUG: should clamp into [lo, hi]\n",
}
E1_TESTS = {
    "tests/test_ops.py": "import unittest\nfrom pkg.ops import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n        self.assertEqual(add(10, 5), 15)\n",
    "tests/test_text.py": "import unittest\nfrom pkg.text import shout\n\n\nclass T(unittest.TestCase):\n    def test_shout(self):\n        self.assertEqual(shout('abc'), 'ABC')\n",
    "tests/test_nums.py": "import unittest\nfrom pkg.nums import clamp\n\n\nclass T(unittest.TestCase):\n    def test_clamp(self):\n        self.assertEqual(clamp(15, 0, 10), 10)\n        self.assertEqual(clamp(-3, 0, 10), 0)\n",
}
E1_TASKS = [
    ("e1_add", "Fix the bug in pkg/ops.py so add(a, b) returns the sum. Do not edit tests.", "tests.test_ops"),
    ("e1_shout", "Fix the bug in pkg/text.py so shout(s) upper-cases the string. Do not edit tests.", "tests.test_text"),
    ("e1_clamp", "Fix the bug in pkg/nums.py so clamp(x, lo, hi) clamps x into [lo, hi]. Do not edit tests.", "tests.test_nums"),
]

# ---- E2 fixture: MULTI-HOP bugs — failing test at api level, root cause 2 hops up the import chain -----
E2_FILES = {
    "deep/__init__.py": "",
    "deep/core.py": "def scale(x):\n    return x * 1   # BUG: should be x * 2\n",
    "deep/ops.py": "from deep.core import scale\n\n\ndef boost(x):\n    return scale(x) + 1\n",
    "deep/api.py": "from deep.ops import boost\n\n\ndef process(xs):\n    return [boost(x) for x in xs]\n",
    "deep/gamma.py": "def gamma(x):\n    return x - 7   # BUG: should be x + 7\n",
    "deep/beta.py": "from deep.gamma import gamma\n\n\ndef beta(x):\n    return gamma(x) * 2\n",
    "deep/alpha.py": "from deep.beta import beta\n\n\ndef alpha(xs):\n    return [beta(x) for x in xs]\n",
}
E2_TESTS = {
    "tests/test_api.py": "import unittest\nfrom deep.api import process\n\n\nclass T(unittest.TestCase):\n    def test_process(self):\n        self.assertEqual(process([1, 2]), [3, 5])\n",
    "tests/test_alpha.py": "import unittest\nfrom deep.alpha import alpha\n\n\nclass T(unittest.TestCase):\n    def test_alpha(self):\n        self.assertEqual(alpha([1, 2]), [16, 18])\n",
}
# (task, test module, the FAILING TEST's entry file → its forward-dep closure is the scope hint)
E2_TASKS = [
    ("e2_api", "The test tests/test_api.py is failing. Find and fix the root-cause bug in the source so it passes. Do not edit tests.",
     "tests.test_api", "deep/api.py"),
    ("e2_alpha", "The test tests/test_alpha.py is failing. Find and fix the root-cause bug in the source so it passes. Do not edit tests.",
     "tests.test_alpha", "deep/alpha.py"),
]

# import graph (forward edges) for E2 scoping — graphify-out/graph.json shape
_GRAPH = {
    "directed": True,
    "nodes": [{"id": m, "source_file": f"deep/{m}.py", "label": f"{m}.py"}
              for m in ("core", "ops", "api", "gamma", "beta", "alpha")],
    "links": [{"source": "api", "target": "ops", "relation": "imports_from"},
              {"source": "ops", "target": "core", "relation": "imports_from"},
              {"source": "alpha", "target": "beta", "relation": "imports_from"},
              {"source": "beta", "target": "gamma", "relation": "imports_from"}],
}


def build_fixture(dst):
    for rel, body in {**E1_FILES, **E1_TESTS, **E2_FILES, **E2_TESTS}.items():
        p = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)
    with open(os.path.join(dst, "tests", "__init__.py"), "w") as f:
        f.write("")
    with open(os.path.join(dst, ".gitignore"), "w") as f:
        f.write("__pycache__/\n*.pyc\n")
    os.makedirs(os.path.join(dst, ".claude"), exist_ok=True)
    with open(os.path.join(dst, ".claude", "settings.json"), "w") as f:
        json.dump({"model": "claude-opus-4-8"}, f)
    os.makedirs(os.path.join(dst, "graphify-out"), exist_ok=True)
    with open(os.path.join(dst, "graphify-out", "graph.json"), "w") as f:
        json.dump(_GRAPH, f)
    g = lambda *a: subprocess.run(["git", "-C", dst, "-c", "user.name=b", "-c", "user.email=b@b", *a],
                                  check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", dst], check=True)
    g("add", "-A"); g("commit", "-qm", "fixture")
    return dst


def forward_closure(start_file):
    """Forward-import closure of start_file over _GRAPH → the files a fix may need to READ."""
    by_file = {n["source_file"]: n["id"] for n in _GRAPH["nodes"]}
    fwd = collections.defaultdict(list)
    for l in _GRAPH["links"]:
        fwd[l["source"]].append(l["target"])
    id_to_file = {n["id"]: n["source_file"] for n in _GRAPH["nodes"]}
    start = by_file.get(start_file)
    seen, out, q = set(), [start_file], collections.deque([start] if start else [])
    while q:
        cur = q.popleft()
        for nxt in fwd.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                out.append(id_to_file[nxt])
                q.append(nxt)
    return sorted(set(out))


def prompt_for(task, scoped_files=None):
    base = (f"You are making a focused change in this repository (cwd).\n\nTASK:\n{task}\n\n"
            "Edit the SOURCE to accomplish it and make the project's tests pass. Do NOT edit tests. "
            "Make the change and stop.")
    if scoped_files:
        base += ("\n\nThe failing test's dependency closure (the only files relevant to this fix) is: "
                 + ", ".join(scoped_files) + ". Focus your reading on these files.")
    return base


def one_call(repo, task, mod, lean=False, scoped_files=None):
    cmd_test = f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m unittest {mod}"
    extra = (LEAN if lean else [])
    for _ in range(3):
        wt = H.checkpoint(repo, "HEAD")
        try:
            argv = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                    *PIN, *extra, prompt_for(task, scoped_files)]
            p = subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=600)
            usage = UM.parse_usage(p.stdout)
            if UM.total_tokens(usage) == 0:
                continue
            res = H.run_tests(wt, cmd_test, timeout=120)
            return {**usage, "resolved": res.get("outcome") == "pass",
                    "total": UM.total_tokens({**UM.empty(), **usage})}
        finally:
            H.discard(repo, wt)
    return {**UM.parse_usage(""), "resolved": False, "total": 0}


def cost_excl_cache_read(u):
    """Conservative real-money floor: cost with cache_read (near-free) removed — opus pricing."""
    return round(u.get("input_tokens", 0) * 5e-6 + u.get("output_tokens", 0) * 25e-6
                 + u.get("cache_creation_input_tokens", 0) * 6.25e-6, 6)


def summarize(pairs, a_key, b_key):
    """Mean ratios b/a across same-model pairs that both resolved."""
    rows = [p for p in pairs if p[a_key]["model"] == p[b_key]["model"]
            and p[a_key]["resolved"] and p[b_key]["resolved"]]
    def ratio(f):
        vals = [f(p[b_key]) / f(p[a_key]) for p in rows if f(p[a_key])]
        return (round(sum(vals) / len(vals), 4), round(min(vals), 4), round(max(vals), 4), len(vals)) if vals else None
    return {"n_clean_pairs": len(rows),
            "fresh_input_ratio": ratio(lambda u: u["input_tokens"]),
            "total_token_ratio": ratio(lambda u: u["total"]),
            "cost_ratio": ratio(lambda u: u["cost_usd"]),
            "cost_excl_cacheread_ratio": ratio(lambda u: cost_excl_cache_read(u))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--out", default="/tmp/e1e2_report.json")
    a = ap.parse_args()
    repo = build_fixture(tempfile.mkdtemp(prefix="e1e2-"))
    report = {"e1": [], "e2": []}
    try:
        # E1 — full vs lean, same model
        for tid, task, mod in E1_TASKS:
            for s in range(a.seeds):
                full = one_call(repo, task, mod, lean=False)
                lean = one_call(repo, task, mod, lean=True)
                report["e1"].append({"task": tid, "seed": s, "full": full, "lean": lean})
                print(f"[E1 {tid} s{s}] full ok={full['resolved']} {full['model']} in={full['input_tokens']} "
                      f"${full['cost_usd']:.4f} | lean ok={lean['resolved']} {lean['model']} in={lean['input_tokens']} ${lean['cost_usd']:.4f}")
        # E2 — full-context vs forward-dep-scoped, same model, full env (isolate the scoping variable)
        for tid, task, mod, entry in E2_TASKS:
            scope = forward_closure(entry)
            for s in range(a.seeds):
                free = one_call(repo, task, mod, lean=False, scoped_files=None)
                scoped = one_call(repo, task, mod, lean=False, scoped_files=scope)
                report["e2"].append({"task": tid, "seed": s, "scope": scope, "free": free, "scoped": scoped})
                print(f"[E2 {tid} s{s}] free ok={free['resolved']} in={free['input_tokens']} ${free['cost_usd']:.4f} | "
                      f"scoped({len(scope)}f) ok={scoped['resolved']} in={scoped['input_tokens']} ${scoped['cost_usd']:.4f}")
        report["e1_summary"] = summarize(report["e1"], "full", "lean")
        report["e2_summary"] = summarize(report["e2"], "free", "scoped")
        json.dump(report, open(a.out, "w"), indent=2)
        print("\n=== E1 (lean/full, same-model clean pairs) ===", json.dumps(report["e1_summary"], indent=2))
        print("\n=== E2 (scoped/free, same-model clean pairs) ===", json.dumps(report["e2_summary"], indent=2))
        print(f"\nreport -> {a.out}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
