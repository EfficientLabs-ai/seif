#!/usr/bin/env python3
"""3-seed significance scale-up. Seed 1 = the existing preds/ (already scored). This runs SEEDS (default
2,3) of every arm over the full 37-instance set into preds/seed<N>/ via SEIF_PREDS, resumable (skips any
prediction already present). claude -p has no seed flag, so a "seed" = an independent stochastic run —
honest, and what reduces per-instance noise toward significance.

Run (background):
  nohup /home/neo/logos-venv/bin/python -u logos/run_seeds.py logos/eval_set_full.json > logs/seeds.log 2>&1 &
"""
import json
import os
import subprocess
import sys
import time

ROOT = "/home/neo/seif/logos"
PY = "/home/neo/logos-venv/bin/python"
EVAL_SET = next((a for a in sys.argv[1:] if a.endswith(".json")), os.path.join(ROOT, "eval_set_full.json"))
SEEDS = [2, 3]
PER_TASK_TIMEOUT = 5400
# (arm prefix, script, extra args) — arm scripts write {prefix}{iid}.jsonl into SEIF_PREDS
ARMS = [
    ("arm_a_", "swe_arm_a.py", []),
    ("arm_b_logos_", "swe_arm_b.py", []),
    ("arm_b_v3_nogate_", "swe_arm_b_v2.py", ["--no-gate"]),
    ("arm_b_v2_", "swe_arm_b_v2.py", []),
]


def _has_patch(fp):
    """A prediction is DONE only if it exists AND carries a non-empty patch. An empty-patch stub (agent
    error / no edit / rate-limit salvage) must be REDONE on resume — file-existence alone is the
    false-complete bug that contaminated the first 3-seed run (whole arms scored 0% on empty patches)."""
    try:
        d = json.loads(open(fp).read().strip().splitlines()[-1])
        return len((d.get("model_patch") or "").strip()) > 0
    except Exception:
        return False


def main():
    instances = json.load(open(EVAL_SET))["instances"]
    print(f"[seeds] {len(instances)} instances × {len(ARMS)} arms × seeds {SEEDS}", flush=True)
    for seed in SEEDS:
        preds = os.path.join(ROOT, "preds", f"seed{seed}")
        os.makedirs(preds, exist_ok=True)
        env = {**os.environ, "SEIF_PREDS": preds, "PYTHONUNBUFFERED": "1"}
        for prefix, script, extra in ARMS:
            todo = [i for i in instances if not _has_patch(os.path.join(preds, f"{prefix}{i}.jsonl"))]
            print(f"[seeds] seed{seed} {prefix.rstrip('_')}: {len(instances)-len(todo)} done (non-empty), "
                  f"{len(todo)} to run", flush=True)
            for n, iid in enumerate(todo, 1):
                t0 = time.monotonic()
                print(f"[seeds] seed{seed} {prefix.rstrip('_')} ({n}/{len(todo)}) {iid}", flush=True)
                try:
                    subprocess.run([PY, os.path.join(ROOT, script), iid, *extra], timeout=PER_TASK_TIMEOUT, env=env)
                except subprocess.TimeoutExpired:
                    print(f"[seeds] WALL-TIMEOUT seed{seed} {prefix} {iid}", flush=True)
                except Exception as e:
                    print(f"[seeds] ERROR seed{seed} {prefix} {iid}: {e!r}", flush=True)
                ok = _has_patch(os.path.join(preds, f"{prefix}{iid}.jsonl"))
                print(f"[seeds]   ({time.monotonic()-t0:.0f}s) patch={'yes' if ok else 'EMPTY'}", flush=True)
    # honest completeness: report non-empty patch counts per seed/arm (not file existence)
    for seed in SEEDS:
        preds = os.path.join(ROOT, "preds", f"seed{seed}")
        counts = {p.rstrip("_"): sum(_has_patch(os.path.join(preds, f"{p}{i}.jsonl")) for i in instances)
                  for p, _, _ in ARMS}
        print(f"[seeds] seed{seed} non-empty: {counts}", flush=True)
    print("[seeds] COMPLETE (counts above = non-empty patches; full = all == n_instances)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
