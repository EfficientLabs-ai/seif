#!/usr/bin/env python3
"""E4 — real-codebase validation.

Answers the red-team's main critique ("toy fixture != real code"): run the levers on the REAL seif repo.
Inject subtle real bugs into real source files (each caught by a real test that ships with the repo), then
have each model fix them in a clean-room of actual main — real files, real imports, real navigation, the
real 192-test env. Measures per-model resolve + cost (does routing / the frontier hold on real code?) and
per-call token composition (is it still ~environment-dominated on a real repo?). Real `claude -p`,
retry-on-empty, full env, only --model varies.
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
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))   # the real seif repo (this worktree)
OPUS, SONNET, HAIKU = "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"
LADDER = [HAIKU, SONNET, OPUS]

# Real, subtle bugs injected into real seif source. (old, new) are exact substrings; raw strings keep
# backslashes literal so they match the file verbatim.
BUGS = [
    dict(id="e4_pipe", file="logos/pr_format.py", test="tests.test_pr_format",
         old=r'.replace("\r", " ").replace("\n", " ").replace("|", "\\|")',
         new=r'.replace("\r", " ").replace("\n", " ")',
         task="tests/test_pr_format.py is failing on markdown table cell escaping. Find and fix the bug in the SOURCE (logos/pr_format.py). Do NOT edit tests."),
    dict(id="e4_chore", file="logos/pr_format.py", test="tests.test_pr_format",
         old='        ctype = "chore"', new="        pass",
         task="tests/test_pr_format.py is failing: an unknown conventional-commit type is not falling back to 'chore'. Find and fix the bug in the SOURCE. Do NOT edit tests."),
    dict(id="e4_totaltok", file="logos/usage_meter.py", test="tests.test_usage_meter",
         old='return sum(int(acc.get(k, 0) or 0) for k in _TOKEN_FIELDS)',
         new='return sum(int(acc.get(k, 0) or 0) for k in _TOKEN_FIELDS if k != "cache_read_input_tokens")',
         task="tests/test_usage_meter.py is failing: total_tokens() is under-counting — a token class is missing from the sum. Find and fix the bug in the SOURCE. Do NOT edit tests."),
]


def inject(wt, bug):
    """Apply the bug to the clean-room file; assert it actually changed something."""
    p = os.path.join(wt, bug["file"])
    src = open(p).read()
    assert bug["old"] in src, f"break anchor not found for {bug['id']} in {bug['file']}"
    broken = src.replace(bug["old"], bug["new"], 1)
    assert broken != src, f"injection was a no-op for {bug['id']}"
    open(p, "w").write(broken)


def prompt_for(task):
    return (f"You are fixing a bug in this repository (cwd).\n\nTASK:\n{task}\n\n"
            "Edit the SOURCE so the failing test passes. Do NOT edit tests. Make the change and stop.")


def one_call(bug, model, timeout=600):
    cmd_test = f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m unittest {bug['test']}"
    for _ in range(3):
        wt = H.checkpoint(REPO, "HEAD")            # clean-room off real main
        try:
            inject(wt, bug)                        # break a real source file
            argv = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                    "--model", model, prompt_for(bug["task"])]
            p = subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=timeout)
            u = UM.parse_usage(p.stdout)
            if UM.total_tokens(u) == 0:
                continue
            res = H.run_tests(wt, cmd_test, timeout=180)
            return {**u, "resolved": res.get("outcome") == "pass"}
        finally:
            H.discard(REPO, wt)
    return {**UM.parse_usage(""), "resolved": False}


def escalate(bug):
    total, resolver, attempts = UM.empty(), None, []
    for model in LADDER:
        r = one_call(bug, model)
        UM.accumulate(total, r)
        attempts.append({"model": model, "resolved": r["resolved"], "cost": r["cost_usd"]})
        if r["resolved"]:
            resolver = model
            break
    return {"resolved": resolver is not None, "resolver": resolver,
            "cost_usd": total["cost_usd"], "attempts": attempts}


def composition(u):
    """Environment share of a call = cached env / total (the ~93% claim, on a real repo)."""
    tot = UM.total_tokens(u)
    env = (u.get("cache_read_input_tokens", 0) or 0) + (u.get("cache_creation_input_tokens", 0) or 0)
    return round(env / tot, 4) if tot else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--out", default="/tmp/e4_report.json")
    a = ap.parse_args()
    matrix, esc = [], []
    for bug in BUGS:
        for s in range(a.seeds):
            for model in (OPUS, SONNET, HAIKU):
                r = one_call(bug, model)
                matrix.append({"bug": bug["id"], "seed": s, "model": model, "resolved": r["resolved"],
                               "cost_usd": r["cost_usd"], "fresh_input": r.get("input_tokens"),
                               "env_share": composition(r)})
                print(f"[E4 {bug['id']:12s} s{s}] {model:30s} ok={r['resolved']} ${r['cost_usd']:.4f} "
                      f"env_share={composition(r)}")
    for bug in BUGS:
        e = escalate(bug); e["bug"] = bug["id"]; esc.append(e)
        print(f"[escalate {bug['id']:12s}] resolved={e['resolved']} by={e['resolver']} ${e['cost_usd']:.4f} "
              f"({'→'.join(x['model'].split('-')[1] for x in e['attempts'])})")

    def per(model):
        rs = [m for m in matrix if m["model"] == model]
        res = sum(1 for m in rs if m["resolved"]); cost = sum(m["cost_usd"] for m in rs)
        envs = [m["env_share"] for m in rs if m["env_share"] is not None]
        return {"runs": len(rs), "resolved": res, "resolve_rate": round(res/len(rs), 3) if rs else None,
                "cost_per_resolved": round(cost/res, 6) if res else None,
                "mean_env_share": round(sum(envs)/len(envs), 4) if envs else None}
    frontier = {m: per(m) for m in (OPUS, SONNET, HAIKU)}
    n = len(esc); eres = sum(1 for e in esc if e["resolved"]); ecost = sum(e["cost_usd"] for e in esc)
    router = {"tasks": n, "resolved": eres, "cost_per_resolved": round(ecost/eres, 6) if eres else None,
              "total_cost": round(ecost, 6),
              "resolver_mix": dict(collections.Counter(e["resolver"] for e in esc))}
    json.dump({"matrix": matrix, "escalation": esc, "frontier": frontier, "router": router},
              open(a.out, "w"), indent=2)
    print("\n=== E4 real-codebase (resolve · $/resolved · mean env-share) ===")
    for m in (OPUS, SONNET, HAIKU):
        f = frontier[m]
        print(f"{m:30s} resolve {f['resolved']}/{f['runs']} ({f['resolve_rate']})  "
              f"$/resolved={f['cost_per_resolved']}  env-share~{f['mean_env_share']}")
    print(f"=== escalation router: resolved {router['resolved']}/{router['tasks']} · "
          f"$/resolved={router['cost_per_resolved']} · mix={router['resolver_mix']}")
    print(f"report -> {a.out}")


if __name__ == "__main__":
    main()
