#!/usr/bin/env python3
"""3-SEED significance + degradation readout (Phase 2 proof foundation).

Single-seed analyze.py answered "direction"; this answers "is it real" by aggregating the completed
3-seed scale-up (seed1 = flat preds/ [already scored], seed2/3 = preds/seed{N}/). For each arm it reports
the per-seed resolve rate, the mean across seeds, a pooled Wilson CI over all seed×instance Bernoulli
trials, and — the honest significance test — a POOLED exact McNemar over every seed×instance paired trial
(3×37=111 pairs per comparison), plus per-seed McNemar so a fragile result can't hide in the pool. Also
the degradation curve (resolve rate by task-length bucket) aggregated across seeds.

Honest caveats stated in the report: instances repeat across seeds (pairs are NOT fully independent — the
pooled p is optimistic vs a mixed model), and "seed" = an independent stochastic claude -p run (no seed
flag). Claim discipline: report the number + the caveat; never round a tie up to a win.

Run with the swebench venv so sys.executable can score:
  /home/neo/logos-venv/bin/python logos/analyze_seeds.py --score logos/eval_set_full.json
  (omit --score to re-read reports already on disk)
"""
import glob
import json
import os
import statistics
import subprocess
import sys

from analyze import DATASET, gold_buckets, mcnemar_exact, wilson  # reuse the vetted stats

HERE = os.path.dirname(os.path.abspath(__file__))
PREDS = os.path.join(HERE, "preds")
REPORT = os.path.join(os.path.dirname(HERE), "logs", "AB_REPORT_3SEED.md")

# arm -> (pred-file prefix, swebench model name used in report filenames)
ARMS = {"arm_a": ("arm_a_", "arm_a_claude_p"),
        "arm_b": ("arm_b_logos_", "arm_b_logos"),
        "arm_b_v3_nogate": ("arm_b_v3_nogate_", "arm_b_v3_nogate"),
        "arm_b_v2": ("arm_b_v2_", "arm_b_v2")}
PAIRS = [("arm_a", "arm_b"), ("arm_a", "arm_b_v2"), ("arm_b", "arm_b_v2"), ("arm_b_v3_nogate", "arm_b_v2")]
LABEL = {"arm_a": "A — blind", "arm_b": "B v1 — feedback+stop-on-green",
         "arm_b_v3_nogate": "B v3 — feedback, NO gate", "arm_b_v2": "B v2 — feedback+independent gate"}
SEEDS = (1, 2, 3)


def seed_dir(seed):
    return PREDS if seed == 1 else os.path.join(PREDS, f"seed{seed}")


def combine(seed, prefix, instances):
    """Concatenate per-instance predictions for one (seed, arm) into a combined jsonl. Returns (path, n)."""
    d = seed_dir(seed)
    out = os.path.join(d, f"_combined_s{seed}_{prefix.rstrip('_')}.jsonl")
    n = 0
    with open(out, "w") as w:
        for iid in instances:
            f = os.path.join(d, f"{prefix}{iid}.jsonl")
            if os.path.exists(f):
                w.write(open(f).read().strip() + "\n")
                n += 1
    return out, n


def _run_id(seed, arm):
    """seed1 reuses the already-scored run naming (ab_<arm>); seeds 2/3 use s<seed>_<arm>. The run_id
    used to SCORE must match the one report_path() reads back — else a fresh score is silently 'missing'."""
    return f"ab_{arm}" if seed == 1 else f"s{seed}_{arm}"


def report_path(seed, arm):
    """Exact, arm- and seed-specific report path (no mtime glob — that could pick a stale/other-run file)."""
    model = ARMS[arm][1]
    p = os.path.join(HERE, f"{model}.{_run_id(seed, arm)}.json")
    return p if os.path.exists(p) else None


def score(seed, arm, instances):
    """Score one (seed, arm) with the official harness if not already on disk (resumable)."""
    existing = report_path(seed, arm)
    if existing:
        return existing
    prefix, model = ARMS[arm]
    combined, n = combine(seed, prefix, instances)
    if n == 0:
        print(f"[s{seed}/{arm}] no predictions on disk — skip", flush=True)
        return None
    run_id = _run_id(seed, arm)
    if n < len(instances):
        print(f"[s{seed}/{arm}] WARNING: only {n}/{len(instances)} predictions present "
              "(missing = unsubmitted = unresolved by SWE-bench convention)", flush=True)
    print(f"[s{seed}/{arm}] scoring {n} predictions (run_id={run_id})", flush=True)
    subprocess.run([sys.executable, "-m", "swebench.harness.run_evaluation",
                    "-d", DATASET, "-s", "test", "-p", combined, "-id", run_id,
                    "-n", "swebench", "--max_workers", "4"], cwd=HERE, check=False)
    return report_path(seed, arm)


def resolved_set(rpt, instances):
    if not rpt or not os.path.exists(rpt):
        return None
    r = json.load(open(rpt))
    return set(r["resolved_ids"]) & set(instances)


def main():
    do_score = "--score" in sys.argv
    eval_set = next((a for a in sys.argv[1:] if a.endswith(".json")), os.path.join(HERE, "eval_set_full.json"))
    instances = json.load(open(eval_set))["instances"]
    n_inst = len(instances)
    if n_inst == 0:
        os.makedirs(os.path.dirname(REPORT), exist_ok=True)
        open(REPORT, "w").write("# 3-seed readout — NO DATA (empty eval set)\n")
        print("empty eval set — nothing to analyze"); return

    # resolved[arm][seed] = set(resolved instance ids), or None if that seed/arm has no report
    resolved = {arm: {} for arm in ARMS}
    for seed in SEEDS:
        for arm in ARMS:
            rpt = score(seed, arm, instances) if do_score else report_path(seed, arm)
            resolved[arm][seed] = resolved_set(rpt, instances)
            if resolved[arm][seed] is None:
                print(f"[s{seed}/{arm}] NO report ({'scored' if do_score else 'on disk'})", flush=True)

    def seeds_with(arm):
        return [s for s in SEEDS if resolved[arm][s] is not None]

    buckets = gold_buckets(instances)
    L = ["# 3-seed A/B significance + degradation — LOGOS execution-feedback eval", ""]
    L.append(f"Eval set: {n_inst} SWE-bench-Verified instances (light repos) × up to 3 seeds. "
             "Grading = official swebench harness on held-out FAIL_TO_PASS/PASS_TO_PASS. "
             "A 'seed' = an independent stochastic `claude -p` run (no seed flag).")
    L.append("")

    # ---- per-arm: per-seed rates, mean across seeds, pooled Wilson over all seed×instance trials ----
    L.append("## Per-arm resolve rate")
    L.append("| arm | seed rates | mean% | pooled k/N | pooled rate% | pooled 95% CI (Wilson) |")
    L.append("|---|---|---|---|---|---|")
    for arm in ARMS:
        sw = seeds_with(arm)
        if not sw:
            L.append(f"| {LABEL[arm]} | — | — | 0/0 | — | — |")
            continue
        per = [len(resolved[arm][s]) / n_inst for s in sw]
        rates_str = " ".join(f"{round(100 * p)}%" for p in per)
        k = sum(len(resolved[arm][s]) for s in sw)
        N = n_inst * len(sw)
        p, lo, hi = wilson(k, N)
        mean = round(100 * statistics.mean(per), 1)
        L.append(f"| {LABEL[arm]} | {rates_str} | {mean} | {k}/{N} | {p} | [{lo}, {hi}] |")
    L.append("")
    L.append("> Pooled CI treats each seed×instance as a Bernoulli trial (expected resolve probability). "
             "Instances repeat across seeds, so pairs below are not fully independent — the pooled p is "
             "optimistic vs a mixed-effects model; per-seed p's guard against a pool-only artifact. "
             "Denominator = all eval instances per seed; an unsubmitted prediction counts as unresolved "
             "(SWE-bench convention).")
    L.append("")

    # ---- degradation curve: resolve rate by task-length bucket, pooled across seeds ----
    L.append("## Degradation curve — resolve rate by task length (gold files touched), pooled across seeds")
    present = [a for a in ARMS if seeds_with(a)]
    L.append("| bucket | inst | " + " | ".join(LABEL[a] for a in present) + " |")
    L.append("|" + "---|" * (2 + len(present)))
    for b in ("single", "multi", "large"):
        ids = [i for i in instances if buckets.get(i) == b]
        if not ids:
            continue
        cells = []
        for a in present:
            sw = seeds_with(a)
            k = sum(sum(i in resolved[a][s] for i in ids) for s in sw)
            N = len(ids) * len(sw)
            cells.append(f"{k}/{N} ({round(100 * k / N) if N else 0}%)")
        L.append(f"| {b} | {len(ids)} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("> The thesis test: does the gate's advantage HOLD (or widen) as task length grows — a flatter "
             "slope than blind — rather than collapsing on multi/large tasks? Read the columns down the buckets.")
    L.append("")

    # ---- pooled + per-seed exact McNemar for each key pair ----
    L.append("## Paired significance — exact McNemar (pooled across seed×instance pairs, + per-seed)")
    for x, y in PAIRS:
        sw = [s for s in SEEDS if resolved[x][s] is not None and resolved[y][s] is not None]
        if not sw:
            continue
        b = sum(sum((i in resolved[x][s]) and (i not in resolved[y][s]) for i in instances) for s in sw)
        c = sum(sum((i in resolved[y][s]) and (i not in resolved[x][s]) for i in instances) for s in sw)
        p_pool = mcnemar_exact(b, c)
        kx = sum(len(resolved[x][s]) for s in sw)
        ky = sum(len(resolved[y][s]) for s in sw)
        delta = round(100 * (ky - kx) / (n_inst * len(sw)), 1)
        sig = "SIGNIFICANT (p<0.05)" if p_pool < 0.05 else "not significant"
        per_seed = []
        for s in sw:
            bs = sum((i in resolved[x][s]) and (i not in resolved[y][s]) for i in instances)
            cs = sum((i in resolved[y][s]) and (i not in resolved[x][s]) for i in instances)
            per_seed.append(f"s{s}:p={mcnemar_exact(bs, cs)}({cs}-{bs})")
        L.append(f"- **{x} vs {y}** (seeds {sw}): {y}-only={c} {x}-only={b} "
                 f"delta({y}-{x})={delta}pp | pooled exact p={p_pool} → **{sig}** | " + "  ".join(per_seed))
    L.append("")
    L.append("_Note: pooled McNemar over repeated instances overstates independence; treat a pooled-significant "
             "result as suggestive unless per-seed p's agree. Honest target stays ≥4–6pp at p<0.05; no 100% claim._")

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    open(REPORT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    main()
