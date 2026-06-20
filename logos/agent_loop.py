#!/usr/bin/env python3
"""LOGOS Phase-1 agentic loop — ONE task, end-to-end, scored on HIDDEN tests, ledgered.

The smallest credible slice: localize -> edit -> run VISIBLE tests -> repeat
(step budget + rollback-on-repetition), then score the final patch against HIDDEN grading
tests the agent never sees, and record the whole lifecycle through the SEIF kernel.

Worker model = `claude -p` (Phase 4 swaps in best-of-3 Claude/Codex/Gemini). Acceptance is decided
by the deterministic hidden-test harness via the kernel artifact gate — never self-reported.

Run:  sg docker -c "python3 logos/agent_loop.py logos/tasks/demo_add"
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kernel"))
import sandbox  # noqa: E402
import seif_kernel as K  # noqa: E402

BUDGET = 4


# Worker model = `claude -p` (headless, OAuth, reliable). The gemini lane is 403
# (unrestricted-key enforcement) until a restricted key propagates. Best-of-3
# (claude/codex/gemini) candidate generation arrives in Phase 4.
CLAUDE_BIN = shutil.which("claude") or "/home/neo/.local/bin/claude"


def model_propose(prompt, timeout=180):
    """Worker model call (claude -p headless). Returns text or '' on failure."""
    try:
        p = subprocess.run([CLAUDE_BIN, "-p", prompt], capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            sys.stderr.write(f"[model] claude rc={p.returncode} err={p.stderr[-300:]}\n")
            return ""
        return p.stdout.strip()
    except Exception as e:
        sys.stderr.write(f"[model] exc {e}\n")
        return ""


def extract_file(resp):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", resp, re.DOTALL)
    body = (m.group(1) if m else resp).strip()
    return body + "\n" if body else ""


def main(task_dir):
    task = json.load(open(os.path.join(task_dir, "task.json")))
    repo, grading = os.path.join(task_dir, "repo"), os.path.join(task_dir, "grading")
    target = task["edit_files"][0]

    for p in (K.EVENTS, K.RECEIPTS, K.APPROVALS, K.DECISIONS, K.ARTIFACTS):  # clean demo ledger
        if p.exists():
            p.unlink()

    work = tempfile.mkdtemp(prefix="logos-loop-")
    workrepo = os.path.join(work, "r")
    shutil.copytree(repo, workrepo)

    tid = "task_" + task["id"]
    K.submit_task({"id": tid, "schema_version": "0.1", "workspace": "logos", "objective": task["objective"],
                   "writable_scope": task["edit_files"], "acceptance": ["hidden grading tests pass"],
                   "output_contract": "artifact", "budget": {"tokens": None, "seconds": None, "usd": None},
                   "state": "DRAFT", "protected": False, "created_by": "claude-worker", "created_at": K._now()})
    for st, who in [("PROPOSED", "claude-architect"), ("VALIDATED", "codex"),
                    ("AUTHORIZED", "neo"), ("EXECUTING", "claude-worker")]:
        K.transition_task({"id": tid}, st, who)

    last_patch, visible_pass = None, False
    for step in range(1, BUDGET + 1):
        r = sandbox.run(workrepo, task["visible_test_cmd"], timeout=30)
        K.append_event("claude-worker", "test.run",
                       {"step": step, "phase": "visible", "outcome": r["outcome"], "rc": r["exit_code"]}, task_id=tid)
        print(f"[step {step}] visible -> {r['outcome']} (rc={r['exit_code']})")
        if r["outcome"] == "pass":
            visible_pass = True
            break
        code = open(os.path.join(workrepo, target)).read()
        prompt = (f"Fix this bug. Objective: {task['objective']}\n\n"
                  f"Current {target}:\n```python\n{code}```\n\n"
                  f"Failing test output:\n{(r['stdout'] + r['stderr'])[:1200]}\n\n"
                  f"Return ONLY the complete corrected contents of {target} in one ```python code block.")
        new = extract_file(model_propose(prompt))
        if not new.strip():
            print("  model returned empty; abort"); break
        if new == last_patch:
            print("  rollback-on-repetition: identical patch -> stuck, abort"); break
        open(os.path.join(workrepo, target), "w").write(new)
        last_patch = new
        K.append_event("claude-worker", "patch.proposed", {"step": step, "file": target, "bytes": len(new)}, task_id=tid)

    # ---- score on HIDDEN grading tests (agent never saw these) ----
    K.transition_task({"id": tid}, "VERIFYING", "hidden-test-harness")
    score = tempfile.mkdtemp(prefix="logos-score-")
    sr = os.path.join(score, "r")
    shutil.copytree(workrepo, sr)
    for gf in os.listdir(grading):
        shutil.copy(os.path.join(grading, gf), sr)
    hidden = sandbox.run(sr, task["hidden_test_cmd"], timeout=30)
    K.append_event("hidden-test-harness", "test.run",
                   {"phase": "hidden", "outcome": hidden["outcome"], "rc": hidden["exit_code"]}, task_id=tid)
    fail_to_pass = hidden["outcome"] == "pass"
    print(f"[score] HIDDEN -> {hidden['outcome']} (rc={hidden['exit_code']})  FAIL_TO_PASS={fail_to_pass}")

    patch_sha = K._sha({"f": last_patch or ""})
    K.record_artifact({"id": "art_" + task["id"], "task_id": tid, "kind": "patch", "content_hash": patch_sha,
                       "produced_by": "claude-worker", "produced_at": K._now(), "reality_state": "STANDALONE",
                       "evidence": [f"visible:{'pass' if visible_pass else 'fail'}", f"hidden:{hidden['outcome']}", f"patch_sha:{patch_sha[:12]}"],
                       "verification": {"tests_passed": bool(fail_to_pass), "reviewed_by": ["hidden-test-harness"],
                                        "verdict": "ACCEPTED" if fail_to_pass else "REJECTED"}})
    K.transition_task({"id": tid}, "ACCEPTED" if fail_to_pass else "REJECTED", "neo")

    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(score, ignore_errors=True)
    print(f"\nRESULT: visible_pass={visible_pass}  FAIL_TO_PASS={fail_to_pass}  final_state={K.project_task(tid)['state']}")
    print(f"chain_ok={K.verify_chain()}")
    print("ledger:")
    for e in K._read(K.EVENTS):
        print(f"  {e['seq']:>2} {e['actor']:<18} {e['type']:<16} {json.dumps(e['payload'])[:60]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "tasks", "demo_add"))
