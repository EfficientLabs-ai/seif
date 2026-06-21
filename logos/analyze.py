#!/usr/bin/env python3
"""Score both arms with the OFFICIAL swebench harness and compute the honest A/B readout:
per-arm resolve rate + Wilson 95% CI, the per-bucket success-vs-task-length degradation curve,
and an exact McNemar paired-significance test. Writes logs/AB_REPORT.md.

Buckets (task-length proxy = gold-patch files touched, NEVER shown to the agent): single<=1, multi<=3, large>3.

Run (after both batches finish):  /home/neo/logos-venv/bin/python logos/analyze.py
  --score   re-run the official scorer on the combined predictions (needs the instance images)
  (default) read the most recent scorer reports already on disk
"""
import glob
import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PREDS = os.path.join(HERE, "preds")
DATASET = "princeton-nlp/SWE-bench_Verified"
EVAL_SET = os.path.join(HERE, "eval_set_20.json")
_js = [a for a in sys.argv[1:] if a.endswith(".json")]
if _js:
    EVAL_SET = _js[0]
REPORT = os.path.join(os.path.dirname(HERE), "logs", "AB_REPORT.md")
ARMS = {"arm_a": ("arm_a_", "arm_a_claude_p"),
        "arm_b": ("arm_b_logos_", "arm_b_logos"),
        "arm_b_v3_nogate": ("arm_b_v3_nogate_", "arm_b_v3_nogate"),
        "arm_b_v2": ("arm_b_v2_", "arm_b_v2")}
# key paired comparisons; v3_nogate-vs-v2 = the moat-decider (gate vs just-more-turns)
PAIRS = [("arm_a", "arm_b"), ("arm_a", "arm_b_v2"), ("arm_b", "arm_b_v2"), ("arm_b_v3_nogate", "arm_b_v2")]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(100 * p, 1), round(100 * (c - h), 1), round(100 * (c + h), 1))


def mcnemar_exact(b, c):
    """Two-sided exact McNemar (binomial, p=0.5 on the b+c discordant pairs)."""
    n = b + c
    if n == 0:
        return 1.0
    lo = min(b, c)
    tail = sum(math.comb(n, k) for k in range(lo + 1)) * (0.5 ** n)
    return round(min(1.0, 2 * tail), 4)


def combine(prefix, instances):
    out = os.path.join(PREDS, f"_combined_{prefix.rstrip('_')}.jsonl")
    n = 0
    with open(out, "w") as w:
        for iid in instances:
            f = os.path.join(PREDS, f"{prefix}{iid}.jsonl")
            if os.path.exists(f):
                w.write(open(f).read().strip() + "\n")
                n += 1
    return out, n


def score(combined, model_name, run_id):
    subprocess.run([sys.executable, "-m", "swebench.harness.run_evaluation",
                    "-d", DATASET, "-s", "test", "-p", combined, "-id", run_id,
                    "-n", "swebench", "--max_workers", "4"], cwd=HERE, check=False)
    rpt = os.path.join(HERE, f"{model_name}.{run_id}.json")
    return rpt if os.path.exists(rpt) else None


def latest_report(model_name):
    cands = sorted(glob.glob(os.path.join(HERE, f"{model_name}.*.json")), key=os.path.getmtime)
    return cands[-1] if cands else None


def gold_buckets(instances):
    from datasets import load_dataset
    ds = {x["instance_id"]: x for x in load_dataset(DATASET, split="test")}
    out = {}
    for iid in instances:
        n = len(set(re.findall(r"^\+\+\+ b/(\S+)", ds[iid]["patch"], re.M)))
        out[iid] = "single" if n <= 1 else ("multi" if n <= 3 else "large")
    return out


def main():
    do_score = "--score" in sys.argv
    es = json.load(open(EVAL_SET))
    instances = es["instances"]
    reports = {}
    for arm, (prefix, model) in ARMS.items():
        if do_score:
            combined, n = combine(prefix, instances)
            if n == 0:
                print(f"[{arm}] no predictions on disk yet — skipping", flush=True)
                reports[arm] = None
                continue
            print(f"[{arm}] scoring {n} predictions -> {combined}", flush=True)
            reports[arm] = score(combined, model, f"ab_{arm}")
        else:
            reports[arm] = latest_report(model)
        if not reports[arm]:
            print(f"[{arm}] NO report found ({'scored' if do_score else 'on disk'}).")
    resolved = {}
    counts = {}
    for arm in ARMS:
        if not reports[arm]:
            resolved[arm] = set(); counts[arm] = (0, 0); continue
        r = json.load(open(reports[arm]))
        res = set(r["resolved_ids"]) & set(instances)
        submitted = set(r["submitted_ids"]) & set(instances)
        resolved[arm] = res
        counts[arm] = (len(res), len(submitted))

    present = [a for a in ARMS if reports.get(a)]   # only arms we actually scored
    buckets = gold_buckets(instances)
    order = ["single", "multi", "large"]
    label = {"arm_a": "A — blind", "arm_b": "B v1 — feedback+stop-on-green",
             "arm_b_v3_nogate": "B v3 — feedback, NO gate (ablation)",
             "arm_b_v2": "B v2 — feedback+independent gate"}
    lines = ["# Arm A vs Arm B (LOGOS) — honest A/B readout", ""]
    lines.append(f"Eval set: {len(instances)} SWE-bench-Verified instances (light repos), 1 seed. "
                 "Grading = official swebench harness on held-out FAIL_TO_PASS/PASS_TO_PASS.")
    lines.append("")
    lines.append("| arm | resolved/scored | rate% | 95% CI (Wilson) |")
    lines.append("|---|---|---|---|")
    for arm in present:
        k, n = counts[arm]
        p, lo, hi = wilson(k, n)
        lines.append(f"| {label.get(arm, arm)} | {k}/{n} | {p} | [{lo}, {hi}] |")
    lines.append("")
    # degradation curve by task-length bucket (one column per present arm)
    lines.append("## Degradation curve — resolve rate by task length (gold files touched)")
    lines.append("| bucket | n | " + " | ".join(label.get(a, a) for a in present) + " |")
    lines.append("|" + "---|" * (2 + len(present)))
    for b in order:
        ids = [i for i in instances if buckets.get(i) == b]
        if not ids:
            continue
        cells = [f"{sum(i in resolved[a] for i in ids)}/{len(ids)}" for a in present]
        lines.append(f"| {b} | {len(ids)} | " + " | ".join(cells) + " |")
    lines.append("")
    # paired significance for each key pair both arms were scored on
    lines.append("## Paired significance (McNemar, exact)")
    for x, y in PAIRS:
        if not (reports.get(x) and reports.get(y)):
            continue
        x_only = sum((i in resolved[x]) and (i not in resolved[y]) for i in instances)
        y_only = sum((i in resolved[y]) and (i not in resolved[x]) for i in instances)
        p = mcnemar_exact(x_only, y_only)
        delta = round(100 * (len(resolved[y]) - len(resolved[x])) / max(1, len(instances)), 1)
        sig = "SIGNIFICANT" if p < 0.05 else f"NOT significant at n={len(instances)}, 1 seed"
        lines.append(f"- **{x} vs {y}**: {y}-only={y_only}  {x}-only={x_only}  "
                     f"delta({y}-{x})={delta}pp  exact p={p}  → {sig}")
    lines.append("")
    for arm in present:
        lines.append(f"resolved by {arm}: {sorted(resolved[arm])}")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    open(REPORT, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    main()
