#!/usr/bin/env python3
"""Resumable Arm-A batch runner. Loops the curated eval set, runs swe_arm_a.py per instance in a
fresh subprocess (full isolation; one crash never kills the batch), and SKIPS any instance whose
predictions file already exists — so re-launching after an interruption resumes where it stopped.

Run (background):  nohup /home/neo/logos-venv/bin/python logos/run_batch.py > logs/arm_a_batch.log 2>&1 &
"""
import json
import os
import subprocess
import sys
import time

ROOT = "/home/neo/seif/logos"
PY = "/home/neo/logos-venv/bin/python"
ARM_A = os.path.join(ROOT, "swe_arm_a.py")
PREDS = os.path.join(ROOT, "preds")
EVAL_SET = os.path.join(ROOT, "eval_set_20.json")
if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
    EVAL_SET = sys.argv[1]
PER_TASK_TIMEOUT = 1100  # hard wall per instance (swe_arm_a's own claude timeout is 900s)


def done(iid):
    return os.path.exists(os.path.join(PREDS, f"arm_a_{iid}.jsonl"))


def main():
    instances = json.load(open(EVAL_SET))["instances"]
    os.makedirs(PREDS, exist_ok=True)
    todo = [i for i in instances if not done(i)]
    print(f"[batch] {len(instances)} total, {len(instances)-len(todo)} already done, {len(todo)} to run", flush=True)
    for n, iid in enumerate(todo, 1):
        t0 = time.monotonic()
        print(f"[batch] ({n}/{len(todo)}) START {iid}", flush=True)
        try:
            subprocess.run([PY, ARM_A, iid], timeout=PER_TASK_TIMEOUT)
        except subprocess.TimeoutExpired:
            print(f"[batch] WALL-TIMEOUT {iid} (>{PER_TASK_TIMEOUT}s) — no preds written, will retry next run", flush=True)
        except Exception as e:  # never let one instance abort the batch
            print(f"[batch] ERROR {iid}: {e!r}", flush=True)
        dt = time.monotonic() - t0
        print(f"[batch] ({n}/{len(todo)}) END   {iid}  ({dt:.0f}s)  preds={'yes' if done(iid) else 'NO'}", flush=True)
    remaining = [i for i in instances if not done(i)]
    print(f"[batch] COMPLETE. {len(instances)-len(remaining)}/{len(instances)} have predictions. "
          f"missing={remaining}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
