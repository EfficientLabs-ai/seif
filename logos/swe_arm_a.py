#!/usr/bin/env python3
"""Arm A — the honest baseline: model ALONE on a SWE-bench-Verified instance.

clone repo@base_commit -> run `claude -p --permission-mode acceptEdits` as the agent
(edits from reasoning; cannot run tests headlessly = a clean BLIND-patch baseline) ->
capture `git diff` as model_patch -> write a predictions jsonl. Scoring is done separately
by the OFFICIAL swebench harness on the held-out FAIL_TO_PASS/PASS_TO_PASS tests.

Arm B (LOGOS) will add sandboxed execution-feedback + verification on top — so the A/B
delta isolates exactly that mechanism. Same model + config in both arms keeps it honest.

Run with the venv python:  /home/neo/logos-venv/bin/python logos/swe_arm_a.py <instance_id>
"""
import json
import os
import subprocess
import sys
import tempfile

from datasets import load_dataset

CLAUDE = "/home/neo/.local/bin/claude"
DATASET = "princeton-nlp/SWE-bench_Verified"
PREDS = "/home/neo/seif/logos/preds"

_DS = None


def get_instance(iid):
    global _DS
    if _DS is None:
        _DS = load_dataset(DATASET, split="test")
    for x in _DS:
        if x["instance_id"] == iid:
            return x
    raise SystemExit(f"instance {iid} not found")


def run_arm_a(iid, timeout=900, check_only=False):
    inst = get_instance(iid)
    print(f"instance={iid} repo={inst['repo']} base={inst['base_commit'][:10]} "
          f"problem_chars={len(inst['problem_statement'])}")
    if check_only:
        print("check-only: instance loads OK; claude bin:", os.path.exists(CLAUDE))
        return
    work = tempfile.mkdtemp(prefix="arm_a_")
    repo = os.path.join(work, "repo")
    subprocess.run(["git", "clone", "--quiet", f"https://github.com/{inst['repo']}.git", repo], check=True)
    subprocess.run(["git", "-C", repo, "checkout", "--quiet", inst["base_commit"]], check=True)
    prompt = (f"You are fixing a real GitHub issue in this repository (cwd).\n\nISSUE:\n"
              f"{inst['problem_statement']}\n\nEdit the source files to fix the issue. "
              "Do NOT modify any test files. Make the change and stop.")
    subprocess.run([CLAUDE, "-p", "--permission-mode", "acceptEdits", prompt],
                   cwd=repo, timeout=timeout, capture_output=True, text=True)
    diff = subprocess.run(["git", "-C", repo, "diff"], capture_output=True, text=True).stdout
    os.makedirs(PREDS, exist_ok=True)
    out = os.path.join(PREDS, f"arm_a_{iid}.jsonl")
    with open(out, "w") as f:
        f.write(json.dumps({"instance_id": iid, "model_name_or_path": "arm_a_claude_p", "model_patch": diff}) + "\n")
    print(f"Arm A {iid}: patch {len(diff)} bytes -> {out}")
    subprocess.run(["rm", "-rf", work])


if __name__ == "__main__":
    iid = next((a for a in sys.argv[1:] if not a.startswith("--")), "psf__requests-2931")
    run_arm_a(iid, check_only="--check" in sys.argv)
