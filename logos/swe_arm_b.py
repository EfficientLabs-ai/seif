#!/usr/bin/env python3
"""Arm B — LOGOS execution-feedback plane on a SWE-bench-Verified instance.

Same history-stripped clone as Arm A (swe_common.prepare_clone) — the ONLY added variable is a
real execution-feedback loop:

  turn 1: claude -p writes `logos_repro.py` (a reproduction of the issue) + fixes the source.
  feedback: the harness runs the repro inside the per-instance SWE-bench testbed (deps installed),
            captures the result, and feeds it back.
  turns 2..N: claude -p continues editing the SOURCE (never the tests) until the repro passes
            or the step budget / repetition guard stops it.

The held-out FAIL_TO_PASS/PASS_TO_PASS tests (test_patch) are never present in the testbed here —
they are applied only by the official scorer at grading time — so the feedback leaks no oracle.
The final source diff (repro scaffold removed, test edits filtered) is written as predictions and
scored by the SAME official swebench harness as Arm A. The A/B delta isolates execution feedback.

Lifecycle is recorded through the SEIF kernel (best-effort; a kernel error never loses eval data).

Run with the venv python:  /home/neo/logos-venv/bin/python logos/swe_arm_b.py <instance_id>
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kernel"))
import swe_common as C          # noqa: E402
import arm_b_testbed as TB      # noqa: E402
try:
    import seif_kernel as K     # noqa: E402
except Exception:               # noqa: BLE001
    K = None

CLAUDE = "/home/neo/.local/bin/claude"
DATASET = "princeton-nlp/SWE-bench_Verified"
PREDS = os.environ.get("SEIF_PREDS") or (os.path.join(HERE, "preds"))
REPRO = "logos_repro.py"
BUDGET = 3              # turn 1 + up to 2 feedback turns
CLAUDE_TIMEOUT = 900
REPRO_TIMEOUT = 180
_DS = None


def get_instance(iid):
    global _DS
    if _DS is None:
        from datasets import load_dataset
        _DS = {x["instance_id"]: x for x in load_dataset(DATASET, split="test")}
    if iid not in _DS:
        raise SystemExit(f"instance {iid} not found")
    return _DS[iid]


def _ledger(fn):
    if K is None:
        return
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - eval data must survive kernel hiccups
        sys.stderr.write(f"[ledger] {e!r}\n")


def run_claude(repo, prompt, timeout=CLAUDE_TIMEOUT):
    try:
        p = subprocess.run([CLAUDE, "-p", "--permission-mode", "acceptEdits", prompt],
                           cwd=repo, timeout=timeout, capture_output=True, text=True)
        return p.returncode, False
    except subprocess.TimeoutExpired:
        return None, True


def turn_prompt(issue, diff, feedback, first):
    if first:
        return (f"You are fixing a real GitHub issue in this repository (cwd).\n\nISSUE:\n{issue}\n\n"
                f"FIRST write a minimal reproduction script named `{REPRO}` at the repo root that "
                "exits non-zero (e.g. an assertion) while the bug is present and exits zero once the "
                "bug is fixed. THEN edit the SOURCE files to fix the issue. Do NOT modify any existing "
                "test files. A separate test environment will run your reproduction and report back.")
    return (f"You are fixing a real GitHub issue in this repository (cwd).\n\nISSUE:\n{issue}\n\n"
            f"CHANGES SO FAR (git diff):\n{diff[:6000]}\n\n"
            f"EXECUTION FEEDBACK — your `{REPRO}` was run in the real test environment:\n{feedback[:4000]}\n\n"
            f"Continue editing the SOURCE files so the reproduction passes (exit 0). Keep `{REPRO}` "
            "updated if needed but do NOT modify any existing test files. Make the change and stop.")


def run_arm_b(iid, check_only=False):
    inst = get_instance(iid)
    print(f"instance={iid} repo={inst['repo']} base={inst['base_commit'][:10]} "
          f"problem_chars={len(inst['problem_statement'])}")
    if check_only:
        print("check-only OK; claude:", os.path.exists(CLAUDE), "image:", TB.image_for(iid))
        return

    img = TB.ensure_image(iid)     # pull prebuilt testbed (raises if unavailable)
    print(f"[arm_b] image ready: {img}")

    work = tempfile.mkdtemp(prefix="arm_b_")
    repo = os.path.join(work, "repo")
    tid = "task_armb_" + iid.replace("__", "_")
    rcs, repro_outcomes, timed = [], [], False
    try:
        C.prepare_clone(inst, repo)
        _ledger(lambda: K.submit_task({
            "id": tid, "schema_version": "0.1", "workspace": "logos-eval", "objective": f"fix {iid}",
            "writable_scope": ["<source>"], "acceptance": ["held-out FAIL_TO_PASS via official harness"],
            "output_contract": "artifact", "budget": {"tokens": None, "seconds": None, "usd": None},
            "state": "DRAFT", "protected": False, "created_by": "claude-worker", "created_at": K._now()}))
        for st, who in [("PROPOSED", "claude-architect"), ("VALIDATED", "codex"),
                        ("AUTHORIZED", "neo"), ("EXECUTING", "claude-worker")]:
            _ledger(lambda st=st, who=who: K.transition_task({"id": tid}, st, who))

        feedback, last_diff, repro_pass = "", None, False
        for step in range(1, BUDGET + 1):
            diff_so_far = C.staged_diff(repo) if step > 1 else ""
            rc, to = run_claude(repo, turn_prompt(inst["problem_statement"], diff_so_far, feedback, step == 1))
            rcs.append(rc)
            timed = timed or to
            _ledger(lambda step=step, rc=rc: K.append_event(
                "claude-worker", "patch.proposed", {"step": step, "agent_rc": rc}, task_id=tid))
            cur_diff = C.staged_diff(repo)
            if step > 1 and cur_diff == last_diff:
                print(f"[arm_b] step {step}: no change since last turn -> stuck, stop")
                break
            last_diff = cur_diff
            if not os.path.exists(os.path.join(repo, REPRO)):
                print(f"[arm_b] step {step}: no {REPRO} yet (agent_rc={rc}, timed_out={to})")
                if step == BUDGET:
                    break
                feedback = f"You have not created {REPRO} yet. Create it and fix the source."
                continue
            r = TB.run_in_testbed(img, repo, f"python {REPRO}", timeout=REPRO_TIMEOUT)
            repro_outcomes.append(r["outcome"])
            feedback = f"exit_code={r['exit_code']} outcome={r['outcome']}\nSTDOUT:\n{r['stdout']}\nSTDERR:\n{r['stderr']}"
            print(f"[arm_b] step {step}: repro -> {r['outcome']} (rc={r['exit_code']}) agent_rc={rc} timed_out={to}")
            _ledger(lambda step=step, r=r: K.append_event(
                "execution-feedback", "test.run",
                {"step": step, "phase": "repro", "outcome": r["outcome"], "rc": r["exit_code"]}, task_id=tid))
            if r["outcome"] == "pass":
                # a passing repro only counts if there is an actual SOURCE fix (repro+tests excluded)
                src = C.filter_tests(C.staged_diff(repo, exclude=[REPRO]))
                if src.strip():
                    repro_pass = True
                    print(f"[arm_b] repro passes at step {step} with a non-empty source fix; stop")
                    break
                print(f"[arm_b] step {step}: repro passes but source diff is EMPTY -> keep going")
                feedback += ("\n\nNOTE: your reproduction passes but you changed NO source file. "
                             "The real fix must live in the SOURCE, not in the reproduction script.")

        # final candidate patch: source-only (repro scaffold excluded by pathspec, test edits filtered)
        raw = C.staged_diff(repo)
        diff = C.filter_tests(C.staged_diff(repo, exclude=[REPRO]))
        base = C.write_prediction(
            PREDS, iid, "arm_b_logos", diff, raw,
            {"agent_rcs": rcs, "timed_out": timed, "steps": len(rcs),
             "repro_outcomes": repro_outcomes, "repro_pass": repro_pass, "image": img})
        _ledger(lambda: K.record_artifact({
            "id": "art_" + tid, "task_id": tid, "kind": "patch", "content_hash": K._sha({"f": diff}),
            "produced_by": "claude-worker", "produced_at": K._now(), "reality_state": "STANDALONE",
            "evidence": [f"repro:{'pass' if repro_pass else 'unverified'}", f"steps:{len(rcs)}",
                         f"patch_bytes:{len(diff)}"],
            "verification": {"tests_passed": False, "reviewed_by": ["execution-feedback"],
                             "verdict": "PENDING_OFFICIAL_SCORE"}}))
        _ledger(lambda: K.transition_task({"id": tid}, "VERIFYING", "official-harness"))
        print(f"Arm B {iid}: steps={len(rcs)} repro_pass={repro_pass} timed_out={timed} "
              f"patch={len(diff)}b (raw {len(raw)}b) -> {base}.jsonl")
    except Exception as e:  # noqa: BLE001 - salvage any work the agent already did after a clean clone
        sys.stderr.write(f"[arm_b] post-clone error: {e!r}; salvaging partial prediction\n")
        try:
            raw = C.staged_diff(repo)
            diff = C.filter_tests(C.staged_diff(repo, exclude=[REPRO]))
            C.write_prediction(PREDS, iid, "arm_b_logos", diff, raw,
                               {"agent_rcs": rcs, "timed_out": timed, "steps": len(rcs),
                                "repro_outcomes": repro_outcomes, "error": repr(e), "salvaged": True})
        except Exception as e2:  # noqa: BLE001 - clone itself failed -> no preds, batch will retry
            sys.stderr.write(f"[arm_b] could not salvage ({e2!r}); leaving unscored for retry\n")
    finally:
        subprocess.run(["rm", "-rf", work])


if __name__ == "__main__":
    iid = next((a for a in sys.argv[1:] if not a.startswith("--")), "psf__requests-2931")
    run_arm_b(iid, check_only="--check" in sys.argv)
