#!/usr/bin/env python3
"""Resumable runner for the NO-GATE ablation arm (arm_b_v3_nogate): same multi-turn execution-feedback
loop as v2 but WITHOUT the independent completeness gate. Isolates whether the win is the GATE or just
"more turns." Skips instances whose arm_b_v3_nogate_<iid>.jsonl already exists.

Run (background):  nohup /home/neo/logos-venv/bin/python -u logos/run_batch_v3.py logos/eval_set_full.json > logs/arm_b_v3_batch.log 2>&1 &
"""
import json
import os
import subprocess
import sys
import time

ROOT = "/home/neo/seif/logos"
PY = "/home/neo/logos-venv/bin/python"
ARM = os.path.join(ROOT, "swe_arm_b_v2.py")
PREDS = os.path.join(ROOT, "preds")
EVAL_SET = os.path.join(ROOT, "eval_set_20.json")
if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
    EVAL_SET = sys.argv[1]
PER_TASK_TIMEOUT = 5400


def done(iid):
    return os.path.exists(os.path.join(PREDS, f"arm_b_v3_nogate_{iid}.jsonl"))


def main():
    instances = json.load(open(EVAL_SET))["instances"]
    os.makedirs(PREDS, exist_ok=True)
    todo = [i for i in instances if not done(i)]
    print(f"[batch-v3] {len(instances)} total, {len(instances)-len(todo)} done, {len(todo)} to run (NO-GATE ablation)", flush=True)
    for n, iid in enumerate(todo, 1):
        t0 = time.monotonic()
        print(f"[batch-v3] ({n}/{len(todo)}) START {iid}", flush=True)
        try:
            subprocess.run([PY, ARM, iid, "--no-gate"], timeout=PER_TASK_TIMEOUT,
                           env={**os.environ, "PYTHONUNBUFFERED": "1"})
        except subprocess.TimeoutExpired:
            print(f"[batch-v3] WALL-TIMEOUT {iid}", flush=True)
        except Exception as e:
            print(f"[batch-v3] ERROR {iid}: {e!r}", flush=True)
        print(f"[batch-v3] ({n}/{len(todo)}) END {iid} ({time.monotonic()-t0:.0f}s) preds={'yes' if done(iid) else 'NO'}", flush=True)
    missing = [i for i in instances if not done(i)]
    print(f"[batch-v3] COMPLETE. {len(instances)-len(missing)}/{len(instances)} have predictions. missing={missing}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
