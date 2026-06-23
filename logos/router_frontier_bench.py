#!/usr/bin/env python3
"""Round 3 (router/frontier) — test the ROUTER, not just cheaper models.

E3/round-2a showed cheaper models match opus on bug-fix-class tasks, but Haiku solved EVERYTHING, so the
escalation path was never exercised and routing-beats-always-Haiku is NOT yet proven. This uses genuinely
hard tasks with a VISIBLE gate (the test the model fixes against) PLUS a WITHHELD ORACLE (a hidden test it
never sees) — so a narrow fix that passes the gate but misses edge cases is caught as a FALSE ACCEPT, the
exact failure an evidence-driven router must handle.

Design: run the MATRIX (task × model × seed); record visible_pass (gate), hidden_pass (oracle), cost, and
the full metric set. Then DERIVE every strategy from the matrix (no extra calls):
  always-haiku / always-sonnet / always-opus · static task-class routing · evidence-escalation (haiku→
  sonnet→opus, accept on VISIBLE pass, escalate on visible fail). Truth = the withheld oracle.
Real `claude -p`; --model pins each arm; retry-on-empty; >=3 seeds.
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
LADDER = [HAIKU, SONNET, OPUS]
# Static task-class routing policy: route by difficulty class (the kind of policy a real router would use).
CLASS_ROUTE = {"medium": HAIKU, "hard": OPUS}

# Each task: visible test (the gate the model sees fail) + hidden test (the withheld oracle). A narrow fix
# can pass `visible` while failing `hidden` → recorded as a FALSE ACCEPT.
def _t(tid, cls, task, src, srcbody, vis_mod, vis_body, hid_mod, hid_body):
    return dict(id=tid, cls=cls, task=task, src=src, srcbody=srcbody,
                vis_mod=vis_mod, vis_body=vis_body, hid_mod=hid_mod, hid_body=hid_body)

TASKS = [
    _t("dedup_last", "hard",
       "Fix pkg/dd.py so dedup(items) keeps the LAST (key,val) per key and preserves first-seen order of surviving keys. Do not edit tests.",
       "pkg/dd.py", "def dedup(items):\n    return items\n",
       "tests.test_dd", "import unittest\nfrom pkg.dd import dedup\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(dedup([(1,'a'),(2,'b'),(1,'c')]), [(1,'c'),(2,'b')])\n",
       "tests.hid_dd", "import unittest\nfrom pkg.dd import dedup\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(dedup([]), [])\n        self.assertEqual(dedup([(1,'a'),(1,'b'),(1,'c')]), [(1,'c')])\n        self.assertEqual(dedup([(1,'a'),(2,'b'),(3,'c'),(2,'x'),(1,'y')]), [(1,'y'),(2,'x'),(3,'c')])\n"),
    _t("role_auth", "hard",
       "Fix pkg/auth.py so can_access(roles, required) honors the hierarchy admin>editor>viewer (a higher role grants lower-required access). Do not edit tests.",
       "pkg/auth.py", "RANK={'viewer':1,'editor':2,'admin':3}\ndef can_access(roles, required):\n    return required in roles\n",
       "tests.test_auth", "import unittest\nfrom pkg.auth import can_access\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertTrue(can_access(['editor'],'editor'))\n        self.assertTrue(can_access(['admin'],'viewer'))\n",
       "tests.hid_auth", "import unittest\nfrom pkg.auth import can_access\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertFalse(can_access(['viewer'],'admin'))\n        self.assertTrue(can_access(['editor'],'viewer'))\n        self.assertFalse(can_access([],'viewer'))\n"),
    _t("migrations", "hard",
       "Fix pkg/mig.py so order(migs) returns migration ids in dependency order (each mig is {id, deps}); deps come before dependents. Do not edit tests.",
       "pkg/mig.py", "def order(migs):\n    return [m['id'] for m in migs]\n",
       "tests.test_mig", "import unittest\nfrom pkg.mig import order\nclass T(unittest.TestCase):\n    def test(self):\n        o=order([{'id':'b','deps':['a']},{'id':'a','deps':[]}])\n        self.assertLess(o.index('a'), o.index('b'))\n",
       "tests.hid_mig", "import unittest\nfrom pkg.mig import order\nclass T(unittest.TestCase):\n    def test(self):\n        # diamond: d depends on b,c; b,c depend on a\n        o=order([{'id':'d','deps':['b','c']},{'id':'b','deps':['a']},{'id':'c','deps':['a']},{'id':'a','deps':[]}])\n        for x in ('a','b','c'): self.assertLess(o.index(x), o.index('d'))\n        self.assertLess(o.index('a'), o.index('b')); self.assertLess(o.index('a'), o.index('c'))\n"),
    _t("api_contract", "hard",
       "pkg/store.py changed: get(key) now returns (value, found) instead of value-or-None. Fix pkg/api.py lookup(store,key) to use the new contract and return value when found else 'MISSING'. Do not edit tests.",
       "pkg/api.py", "from pkg.store import get\ndef lookup(store, key):\n    v = get(store, key)\n    return v if v else 'MISSING'\n",
       "tests.test_api", "import unittest\nfrom pkg.api import lookup\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(lookup({'x':5},'x'), 5)\n        self.assertEqual(lookup({},'y'), 'MISSING')\n",
       "tests.hid_api", "import unittest\nfrom pkg.api import lookup\nclass T(unittest.TestCase):\n    def test(self):\n        # falsy-but-present values must NOT read as missing (the old `if v` bug)\n        self.assertEqual(lookup({'a':0},'a'), 0)\n        self.assertEqual(lookup({'b':''},'b'), '')\n        self.assertEqual(lookup({'c':False},'c'), False)\n"),
    _t("paginate", "medium",
       "Fix pkg/pg.py so page(items, size, n) returns the n-th 1-indexed page of given size. Do not edit tests.",
       "pkg/pg.py", "def page(items, size, n):\n    return items[n*size:(n+1)*size]\n",
       "tests.test_pg", "import unittest\nfrom pkg.pg import page\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(page([1,2,3,4,5,6], 2, 2), [3,4])\n",
       "tests.hid_pg", "import unittest\nfrom pkg.pg import page\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(page([1,2,3,4,5], 2, 1), [1,2])\n        self.assertEqual(page([1,2,3,4,5], 2, 3), [5])\n        self.assertEqual(page([1,2,3], 2, 9), [])\n"),
]

# store.py for the api_contract task (the "changed" dependency the model must adapt to).
_STORE = "def get(store, key):\n    return (store[key], True) if key in store else (None, False)\n"


def build_fixture(dst):
    os.makedirs(os.path.join(dst, "pkg"), exist_ok=True)
    os.makedirs(os.path.join(dst, "tests"), exist_ok=True)
    open(os.path.join(dst, "pkg", "__init__.py"), "w").close()
    open(os.path.join(dst, "tests", "__init__.py"), "w").close()
    open(os.path.join(dst, "pkg", "store.py"), "w").write(_STORE)
    open(os.path.join(dst, ".gitignore"), "w").write("__pycache__/\n*.pyc\n")
    for t in TASKS:
        open(os.path.join(dst, t["src"]), "w").write(t["srcbody"])
        open(os.path.join(dst, t["vis_mod"].replace(".", "/") + ".py"), "w").write(t["vis_body"])
    g = lambda *a: subprocess.run(["git", "-C", dst, "-c", "user.name=b", "-c", "user.email=b@b", *a],
                                  check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", dst], check=True)
    g("add", "-A"); g("commit", "-qm", "fixture")
    return dst


def _runtest(wt, mod):
    cmd = f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m unittest {mod}"
    return H.run_tests(wt, cmd, timeout=120).get("outcome") == "pass"


def prompt_for(task):
    return (f"You are making a focused change in this repository (cwd).\n\nTASK:\n{task}\n\n"
            "Edit the SOURCE to accomplish it and make the project's tests pass. Do NOT edit tests. "
            "Make the change and stop.")


def one_call(repo, t, model, timeout=600):
    """Fix against the VISIBLE gate; then run the WITHHELD oracle. resolved = visible AND hidden;
    false_accept = visible AND NOT hidden. retry-on-empty; --model pins the arm."""
    for _ in range(3):
        wt = H.checkpoint(repo, "HEAD")
        try:
            argv = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                    "--model", model, prompt_for(t["task"])]
            p = subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=timeout)
            u = UM.parse_usage(p.stdout)
            if UM.total_tokens(u) == 0:
                continue
            visible = _runtest(wt, t["vis_mod"])
            # withheld oracle: write the hidden test ONLY now (the model never saw it) and run it
            open(os.path.join(wt, t["hid_mod"].replace(".", "/") + ".py"), "w").write(t["hid_body"])
            hidden = _runtest(wt, t["hid_mod"]) if visible else False
            return {"visible": visible, "hidden": hidden, "cost_usd": u.get("cost_usd", 0.0),
                    "model_actual": u.get("model"), "mismatch": (u.get("model") or "").split("[")[0] != model}
        finally:
            H.discard(repo, wt)
    return {"visible": False, "hidden": False, "cost_usd": 0.0, "model_actual": None, "mismatch": True}


def derive_strategies(matrix):
    """From the per-(task,seed,model) matrix, derive each strategy's outcome WITHOUT extra calls.
    Truth = the withheld oracle (hidden). Evidence-escalation accepts on VISIBLE pass (the gate)."""
    keys = sorted({(r["task"], r["seed"]) for r in matrix})
    by = {(r["task"], r["seed"], r["model"]): r for r in matrix}
    cls = {r["task"]: r["cls"] for r in matrix}   # task-class from the matrix itself (decoupled from TASKS)
    strat = {}

    def acc(name, rows):
        n = len(rows)
        resolved = sum(1 for r in rows if r["resolved"])
        false_acc = sum(1 for r in rows if r["false_accept"])
        cost = sum(r["cost"] for r in rows)
        return {name: {"tasks": n, "resolved": resolved, "resolve_rate": round(resolved / n, 3) if n else None,
                       "false_accepts": false_acc, "cost_per_resolved": round(cost / resolved, 6) if resolved else None,
                       "total_cost": round(cost, 6)}}

    for m in (HAIKU, SONNET, OPUS):
        rows = [{"resolved": by[(t, s, m)]["resolved"], "false_accept": by[(t, s, m)]["false_accept"],
                 "cost": by[(t, s, m)]["cost_usd"]} for (t, s) in keys]
        strat.update(acc(f"always:{m.split('-')[1]}", rows))

    static = []
    for (t, s) in keys:
        m = CLASS_ROUTE[cls[t]]
        r = by[(t, s, m)]
        static.append({"resolved": r["resolved"], "false_accept": r["false_accept"], "cost": r["cost_usd"]})
    strat.update(acc("static-route", static))

    esc, esc_mix, esc_attempts = [], collections.Counter(), []
    for (t, s) in keys:
        cost, accepted_model, accepted = 0.0, None, None
        attempts = 0
        for m in LADDER:
            r = by[(t, s, m)]; cost += r["cost_usd"]; attempts += 1
            if r["visible"]:                      # router accepts on the gate (visible evidence)
                accepted_model, accepted = m, r
                break
        if accepted is None:                      # nobody passed the gate → take last rung's result
            accepted_model, accepted = LADDER[-1], by[(t, s, LADDER[-1])]
        esc_mix[accepted_model] += 1
        esc_attempts.append(attempts)
        esc.append({"resolved": accepted["resolved"], "false_accept": accepted["false_accept"], "cost": cost})
    e = acc("escalation", esc)["escalation"]
    e["resolver_mix"] = {k.split('-')[1]: v for k, v in esc_mix.items()}
    e["mean_attempts"] = round(sum(esc_attempts) / len(esc_attempts), 2) if esc_attempts else None
    strat["escalation"] = e
    return strat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", default="/tmp/router_report.json")
    ap.add_argument("--jsonl", default="/tmp/router_rows.jsonl")
    a = ap.parse_args()
    repo = build_fixture(tempfile.mkdtemp(prefix="router-"))
    matrix = []
    jf = open(a.jsonl, "w")
    try:
        for t in TASKS:
            for s in range(a.seeds):
                for model in LADDER:
                    r = one_call(repo, t, model)
                    row = {"task": t["id"], "cls": t["cls"], "seed": s, "model": model,
                           "visible": r["visible"], "hidden": r["hidden"],
                           "resolved": r["visible"] and r["hidden"],
                           "false_accept": r["visible"] and not r["hidden"],
                           "cost_usd": r["cost_usd"], "model_actual": r["model_actual"], "mismatch": r["mismatch"]}
                    matrix.append(row)
                    jf.write(json.dumps(row) + "\n"); jf.flush()
                    print(f"[router {t['id']:12s} {t['cls']:6s} s{s} {model.split('-')[1]:6s}] "
                          f"vis={r['visible']:d} hid={r['hidden']:d} "
                          f"{'FALSE_ACCEPT ' if (r['visible'] and not r['hidden']) else ''}${r['cost_usd']:.4f}")
        strat = derive_strategies(matrix)
        json.dump({"matrix": matrix, "strategies": strat,
                   "model_mismatches": sum(1 for r in matrix if r["mismatch"])}, open(a.out, "w"), indent=2)
        print("\n=== STRATEGIES (resolve-rate · $/resolved · false-accepts) — truth = withheld oracle ===")
        for name, d in strat.items():
            extra = f" mix={d.get('resolver_mix')} attempts~{d.get('mean_attempts')}" if "resolver_mix" in d else ""
            print(f"{name:18s} resolve={d['resolve_rate']} ({d['resolved']}/{d['tasks']})  "
                  f"$/resolved={d['cost_per_resolved']}  false_accepts={d['false_accepts']}{extra}")
        print(f"\nreport -> {a.out}")
    finally:
        jf.close()
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
