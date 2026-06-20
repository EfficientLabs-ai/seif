#!/usr/bin/env python3
"""Resumable Arm-B v2 batch runner — same eval set + resumability as the others, each instance runs
swe_arm_b_v2.py (feedback loop + independent completeness gate) and is SKIPPED when its
arm_b_v2_<iid>.jsonl already exists.

Run (background):  nohup /home/neo/logos-venv/bin/python -u logos/run_batch_b_v2.py > logs/arm_b_v2_batch.log 2>&1 &
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
PER_TASK_TIMEOUT = 5400  # up to 4 claude turns (900s) + repro runs + Codex gate calls


def done(iid):
    return os.path.exists(os.path.join(PREDS, f"arm_b_v2_{iid}.jsonl"))


def main():
    instances = json.load(open(EVAL_SET))["instances"]
    os.makedirs(PREDS, exist_ok=True)
    todo = [i for i in instances if not done(i)]
    print(f"[batch-v2] {len(instances)} total, {len(instances)-len(todo)} already done, {len(todo)} to run", flush=True)
    for n, iid in enumerate(todo, 1):
        t0 = time.monotonic()
        print(f"[batch-v2] ({n}/{len(todo)}) START {iid}", flush=True)
        try:
            subprocess.run([PY, ARM, iid], timeout=PER_TASK_TIMEOUT,
                           env={**os.environ, "PYTHONUNBUFFERED": "1"})
        except subprocess.TimeoutExpired:
            print(f"[batch-v2] WALL-TIMEOUT {iid} (>{PER_TASK_TIMEOUT}s) — will retry next run", flush=True)
        except Exception as e:
            print(f"[batch-v2] ERROR {iid}: {e!r}", flush=True)
        dt = time.monotonic() - t0
        print(f"[batch-v2] ({n}/{len(todo)}) END   {iid}  ({dt:.0f}s)  preds={'yes' if done(iid) else 'NO'}", flush=True)
    remaining = [i for i in instances if not done(i)]
    print(f"[batch-v2] COMPLETE. {len(instances)-len(remaining)}/{len(instances)} have predictions. "
          f"missing={remaining}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
