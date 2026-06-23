#!/usr/bin/env python3
"""E3 — model routing as its own MEASURED lever.

Hold context constant (full environment), vary ONLY the model (opus / sonnet / haiku) across the same
tasks x seeds. The honest metric is COST-PER-RESOLVED-task, not cost-per-call: a cheaper model that fails
more can cost more once you count the misses. Reuses the e1e2 fixture + the merged usage_meter. Real
`claude -p`; retry-on-empty for the nested-claude empty-output flakiness.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1e2_bench as E       # noqa: E402  (build_fixture, E1_TASKS — merged in #31)
import project_harness as H  # noqa: E402
import usage_meter as UM     # noqa: E402

CLAUDE = "/home/neo/.local/bin/claude"
MODELS = ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]


def prompt_for(task):
    return (f"You are making a focused change in this repository (cwd).\n\nTASK:\n{task}\n\n"
            "Edit the SOURCE to accomplish it and make the project's tests pass. Do NOT edit tests. "
            "Make the change and stop.")


def one_call(repo, task, mod, model, timeout=600):
    """One metered edit on a FIXED model, FULL environment (only --model varies). Retry-on-empty (max 3)."""
    cmd_test = f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m unittest {mod}"
    for _ in range(3):
        wt = H.checkpoint(repo, "HEAD")
        try:
            argv = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                    "--model", model, prompt_for(task)]
            p = subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=timeout)
            usage = UM.parse_usage(p.stdout)
            if UM.total_tokens(usage) == 0:
                continue
            res = H.run_tests(wt, cmd_test, timeout=120)
            return {**usage, "resolved": res.get("outcome") == "pass",
                    "total": UM.total_tokens({**UM.empty(), **usage})}
        finally:
            H.discard(repo, wt)
    return {**UM.parse_usage(""), "resolved": False, "total": 0}


def summarize(rows):
    """Per-model: resolve rate + total $ + cost-per-RESOLVED + mean total tokens (only rows that ran)."""
    out = {}
    for model in MODELS:
        rs = [r for r in rows if r["model_requested"] == model and r["total"] > 0]
        n = len(rs)
        resolved = sum(1 for r in rs if r["resolved"])
        cost = round(sum(r["cost_usd"] for r in rs), 6)
        out[model] = {
            "runs": n,
            "resolved": resolved,
            "resolve_rate": round(resolved / n, 3) if n else None,
            "total_cost_usd": cost,
            "cost_per_call": round(cost / n, 6) if n else None,
            "cost_per_resolved": round(cost / resolved, 6) if resolved else None,
            "mean_total_tokens": round(sum(r["total"] for r in rs) / n) if n else None,
            "served_model": next((r["model"] for r in rs if r.get("model")), None),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--out", default="/tmp/e3_report.json")
    a = ap.parse_args()
    repo = E.build_fixture(tempfile.mkdtemp(prefix="e3-"))
    rows = []
    try:
        for tid, task, mod in E.E1_TASKS:
            for s in range(a.seeds):
                for model in MODELS:
                    r = one_call(repo, task, mod, model)
                    r.update({"task": tid, "seed": s, "model_requested": model})
                    rows.append(r)
                    print(f"[E3 {tid} s{s}] {model:32s} ok={r['resolved']} served={r.get('model')} "
                          f"total={r['total']} ${r['cost_usd']:.4f}")
        summary = summarize(rows)
        json.dump({"rows": rows, "summary": summary}, open(a.out, "w"), indent=2)
        print("\n=== E3 model-routing summary (same task/context, only model varies) ===")
        for m, d in summary.items():
            print(f"{m:32s} resolve {d['resolved']}/{d['runs']} ({d['resolve_rate']})  "
                  f"$/call={d['cost_per_call']}  $/RESOLVED={d['cost_per_resolved']}  tok~{d['mean_total_tokens']}")
        print(f"\nreport -> {a.out}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
