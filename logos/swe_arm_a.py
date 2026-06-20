#!/usr/bin/env python3
"""Arm A — the honest baseline: model ALONE on a SWE-bench-Verified instance.

clone repo@base_commit -> STRIP .git history (so the agent can't read the upstream fix) ->
run `claude -p --permission-mode acceptEdits` (edits from reasoning; no headless test
execution = clean BLIND-patch baseline) -> stage ALL changes incl. new files -> drop any
test-file edits -> write predictions jsonl. Scored separately by the OFFICIAL swebench harness
on held-out FAIL_TO_PASS/PASS_TO_PASS tests.

Arm B (LOGOS) adds sandboxed execution-feedback + verify on top; the A/B delta isolates that.
NOTE: Arm B MUST use the identical history-stripped clone for the comparison to be fair.
Hardened per Codex review C-armA-1 (staged diff, test-edit filter, robust rc/timeout/cleanup, no-history).

Run with the venv python:  /home/neo/logos-venv/bin/python logos/swe_arm_a.py <instance_id>
"""
import json
import os
import re
import subprocess
import sys
import tempfile

from datasets import load_dataset

CLAUDE = "/home/neo/.local/bin/claude"
DATASET = "princeton-nlp/SWE-bench_Verified"
PREDS = "/home/neo/seif/logos/preds"
TEST_RE = re.compile(r"(^|/)tests?/|(^|/)conftest\.py$|(^|/)test_[^/]*\.py$|_test\.py$")
_DS = None


def get_instance(iid):
    global _DS
    if _DS is None:
        _DS = {x["instance_id"]: x for x in load_dataset(DATASET, split="test")}
    if iid not in _DS:
        raise SystemExit(f"instance {iid} not found")
    return _DS[iid]


def filter_tests(diff):
    """Drop per-file diff sections touching test paths — the agent must not edit graded tests."""
    out, keep = [], True
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            keep = not (m and TEST_RE.search(m.group(2)))
        if keep:
            out.append(line)
    return "".join(out)


def run_arm_a(iid, timeout=900, check_only=False):
    inst = get_instance(iid)
    print(f"instance={iid} repo={inst['repo']} base={inst['base_commit'][:10]} "
          f"problem_chars={len(inst['problem_statement'])}")
    if check_only:
        print("check-only OK; claude bin:", os.path.exists(CLAUDE))
        return
    work = tempfile.mkdtemp(prefix="arm_a_")
    try:
        repo = os.path.join(work, "repo")
        subprocess.run(["git", "clone", "--quiet", f"https://github.com/{inst['repo']}.git", repo], check=True)
        subprocess.run(["git", "-C", repo, "checkout", "--quiet", inst["base_commit"]], check=True)
        # strip history (no upstream-fix leak) and re-init a clean base so `git diff` still works
        subprocess.run(["rm", "-rf", os.path.join(repo, ".git")], check=True)
        for c in (["git", "-C", repo, "init", "-q"],
                  ["git", "-C", repo, "add", "-A"],
                  ["git", "-C", repo, "-c", "user.name=base", "-c", "user.email=b@b", "commit", "-q", "-m", "base"]):
            subprocess.run(c, check=True, capture_output=True)
        prompt = (f"You are fixing a real GitHub issue in this repository (cwd).\n\nISSUE:\n"
                  f"{inst['problem_statement']}\n\nEdit the source files to fix the issue. "
                  "Do NOT modify any test files. Make the change and stop.")
        rc, timed = None, False
        try:
            p = subprocess.run([CLAUDE, "-p", "--permission-mode", "acceptEdits", prompt],
                               cwd=repo, timeout=timeout, capture_output=True, text=True)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            timed = True
        subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)        # stage incl. NEW files
        raw = subprocess.run(["git", "-C", repo, "diff", "--cached"], capture_output=True, text=True).stdout
        diff = filter_tests(raw)                                                       # drop test edits
        os.makedirs(PREDS, exist_ok=True)
        with open(os.path.join(PREDS, f"arm_a_{iid}.jsonl"), "w") as f:
            f.write(json.dumps({"instance_id": iid, "model_name_or_path": "arm_a_claude_p", "model_patch": diff}) + "\n")
        json.dump({"instance_id": iid, "agent_rc": rc, "timed_out": timed, "patch_bytes": len(diff),
                   "raw_bytes": len(raw), "empty": not diff.strip()},
                  open(os.path.join(PREDS, f"arm_a_{iid}.meta.json"), "w"))
        print(f"Arm A {iid}: rc={rc} timed_out={timed} patch={len(diff)}b (raw {len(raw)}b)")
    finally:
        subprocess.run(["rm", "-rf", work])


def _selftest():
    d = ("diff --git a/src/calc.py b/src/calc.py\n-old\n+new\n"
         "diff --git a/tests/test_calc.py b/tests/test_calc.py\n-x\n+y\n"
         "diff --git a/conftest.py b/conftest.py\n-a\n+b\n"
         "diff --git a/pkg/util_test.py b/pkg/util_test.py\n-m\n+n\n")
    f = filter_tests(d)
    assert "src/calc.py" in f, "kept source"
    assert "tests/test_calc.py" not in f and "conftest.py" not in f and "util_test.py" not in f, f
    print("filter_tests selftest PASS (source kept, tests dropped)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        iid = next((a for a in sys.argv[1:] if not a.startswith("--")), "psf__requests-2931")
        run_arm_a(iid, check_only="--check" in sys.argv)
