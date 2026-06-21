#!/usr/bin/env python3
"""Resumable Arm-B (LOGOS) batch runner — same eval set and resumability model as run_batch.py,
but each instance runs swe_arm_b.py (clone + execution-feedback loop) and is SKIPPED when its
arm_b_logos_<iid>.jsonl already exists. One crash never kills the batch.

Run (background):  nohup /home/neo/logos-venv/bin/python logos/run_batch_b.py > logs/arm_b_batch.log 2>&1 &
"""
import json
import os
import subprocess
import sys
import time

ROOT = "/home/neo/seif/logos"
PY = "/home/neo/logos-venv/bin/python"
ARM_B = os.path.join(ROOT, "swe_arm_b.py")
PREDS = os.path.join(ROOT, "preds")
EVAL_SET = os.path.join(ROOT, "eval_set_20.json")
PER_TASK_TIMEOUT = 3600  # up to 3 claude turns (900s each) + testbed runs + image pull


def done(iid):
    return os.path.exists(os.path.join(PREDS, f"arm_b_logos_{iid}.jsonl"))


def main():
    instances = json.load(open(EVAL_SET))["instances"]
    os.makedirs(PREDS, exist_ok=True)
    todo = [i for i in instances if not done(i)]
    print(f"[batch-b] {len(instances)} total, {len(instances)-len(todo)} already done, {len(todo)} to run", flush=True)
    for n, iid in enumerate(todo, 1):
        t0 = time.monotonic()
        print(f"[batch-b] ({n}/{len(todo)}) START {iid}", flush=True)
        try:
            subprocess.run([PY, ARM_B, iid], timeout=PER_TASK_TIMEOUT,
                           env={**os.environ, "PYTHONUNBUFFERED": "1"})
        except subprocess.TimeoutExpired:
            print(f"[batch-b] WALL-TIMEOUT {iid} (>{PER_TASK_TIMEOUT}s) — will retry next run", flush=True)
        except Exception as e:
            print(f"[batch-b] ERROR {iid}: {e!r}", flush=True)
        dt = time.monotonic() - t0
        print(f"[batch-b] ({n}/{len(todo)}) END   {iid}  ({dt:.0f}s)  preds={'yes' if done(iid) else 'NO'}", flush=True)
    remaining = [i for i in instances if not done(i)]
    print(f"[batch-b] COMPLETE. {len(instances)-len(remaining)}/{len(instances)} have predictions. "
          f"missing={remaining}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
