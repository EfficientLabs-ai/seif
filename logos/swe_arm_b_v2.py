#!/usr/bin/env python3
"""Arm B v2 — LOGOS execution-feedback + INDEPENDENT COMPLETENESS GATE.

Targets the measured Finding-001 pathology (FINDINGS_001.md): v1 stopped the instant the agent's
self-authored repro passed, shipping NARROW patches that pass a repro scoped to a partial fix. v2:

  (1) KILL stop-on-green — a passing repro no longer ends the loop by itself.
  (2) INDEPENDENT COMPLETENESS GATE — when the repro passes with a non-empty source fix, an
      independent reviewer (Codex, via `codex exec`, read-only, structured verdict) judges whether the
      SOURCE diff COMPLETELY resolves the whole issue. Only a COMPLETE verdict stops the loop; an
      INCOMPLETE verdict feeds the reviewer's "what's missing" back to the agent to keep fixing.

Everything else is identical to Arm A / Arm B v1: same clone (swe_common.prepare_clone), same testbed
execution (arm_b_testbed), held-out grading tests never present here, final source-only patch scored by
the official harness. The gate judges only the diff (no oracle access). Lifecycle ledgered via the kernel.

Run:  /home/neo/logos-venv/bin/python logos/swe_arm_b_v2.py <instance_id>
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
CODEX = "/home/neo/.nvm/versions/node/v22.22.3/bin/codex"
DATASET = "princeton-nlp/SWE-bench_Verified"
PREDS = os.environ.get("SEIF_PREDS") or (os.path.join(HERE, "preds"))
REPRO = "logos_repro.py"
BUDGET = 4                 # turn 1 + up to 3 gate/repro-driven refinements (no early stop on repro pass)
CLAUDE_TIMEOUT = 900
REPRO_TIMEOUT = 180
GATE_TIMEOUT = 240
_DS = None

_GATE_SCHEMA = os.path.join(tempfile.gettempdir(), "logos_gate_schema.json")
json.dump({"type": "object", "additionalProperties": False, "required": ["verdict", "missing"],
           "properties": {"verdict": {"type": "string", "enum": ["COMPLETE", "INCOMPLETE"]},
                          "missing": {"type": "string"}}}, open(_GATE_SCHEMA, "w"))


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
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[ledger] {e!r}\n")


def run_claude(repo, prompt, timeout=CLAUDE_TIMEOUT):
    try:
        p = subprocess.run([CLAUDE, "-p", "--permission-mode", "acceptEdits", prompt],
                           cwd=repo, timeout=timeout, capture_output=True, text=True)
        return p.returncode, False
    except subprocess.TimeoutExpired:
        return None, True


def _parse_verdict(stdout):
    """Robustly pull {verdict, missing} from codex stdout: last JSON line -> whole-blob JSON -> regex."""
    import re
    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    for l in reversed(lines):                      # 1: last single-line JSON object with a verdict
        if l.startswith("{") and l.endswith("}"):
            try:
                c = json.loads(l)
                if isinstance(c, dict) and "verdict" in c:
                    return c["verdict"], c.get("missing", "")
            except json.JSONDecodeError:
                pass
    try:                                           # 2: whole stdout as one (pretty/multiline) JSON object
        c = json.loads(stdout)
        if isinstance(c, dict) and "verdict" in c:
            return c["verdict"], c.get("missing", "")
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r'"verdict"\s*:\s*"(COMPLETE|INCOMPLETE)"', stdout)  # 3: regex fallback
    if m:
        mm = re.search(r'"missing"\s*:\s*"((?:[^"\\]|\\.)*)"', stdout)
        return m.group(1), (mm.group(1) if mm else "")
    return None, None


def _codex_gate_once(prompt):
    p = subprocess.run(
        [CODEX, "exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral", "--color", "never",
         "--output-schema", _GATE_SCHEMA, prompt],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=GATE_TIMEOUT)
    v, missing = _parse_verdict(p.stdout)
    if v in ("COMPLETE", "INCOMPLETE"):
        return v, missing
    return "ERROR", f"no verdict (rc={p.returncode}); stderr={p.stderr[-160:]}"


def codex_gate(issue, src_diff):
    """Independent completeness review of the SOURCE diff vs the issue (read-only, structured).
    Retries once on ERROR. Returns (verdict, missing). ERROR is handled FAIL-CLOSED by the caller
    (keep refining; never accept on a gate error) so an infra/parse blip can't ship an incomplete fix."""
    prompt = ("You are an INDEPENDENT senior reviewer. A coding agent proposed a fix for the GitHub "
              "issue below. Judge ONLY whether the proposed SOURCE diff COMPLETELY resolves the ENTIRE "
              "issue — every case it describes, not just the obvious one. Do NOT require tests. If "
              "anything the issue describes is left unaddressed, or the fix is too narrow, return "
              "verdict=INCOMPLETE and state precisely what is missing. If it fully resolves the issue, "
              f"return verdict=COMPLETE.\n\nISSUE:\n{issue}\n\nPROPOSED SOURCE DIFF:\n{src_diff[:9000]}\n\n"
              "Respond per the schema.")
    for attempt in (1, 2):
        try:
            v, missing = _codex_gate_once(prompt)
            if v != "ERROR":
                return v, missing
            sys.stderr.write(f"[gate] attempt {attempt} ERROR: {missing}\n")
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"[gate] attempt {attempt} timeout\n")
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[gate] attempt {attempt} exc {e!r}\n")
    return "ERROR", "gate unavailable after retry"


def turn_prompt(issue, diff, feedback, first):
    if first:
        return (f"You are fixing a real GitHub issue in this repository (cwd).\n\nISSUE:\n{issue}\n\n"
                f"FIRST write a minimal reproduction script named `{REPRO}` at the repo root that exits "
                "non-zero while the bug is present and exits zero once it is fixed. THEN edit the SOURCE "
                "files to COMPLETELY fix the issue — handle every case it describes, not just the obvious "
                "one. Do NOT modify any existing test files. A test environment + an independent reviewer "
                "will check your work.")
    return (f"You are fixing a real GitHub issue in this repository (cwd).\n\nISSUE:\n{issue}\n\n"
            f"CHANGES SO FAR (git diff):\n{diff[:6000]}\n\nFEEDBACK:\n{feedback[:4500]}\n\n"
            f"Continue editing the SOURCE files to COMPLETELY fix the issue. Address the feedback. Keep "
            f"`{REPRO}` updated if needed, but do NOT modify existing test files and do NOT hide the fix "
            "in the reproduction. Make the change and stop.")


def run_arm_b_v2(iid, check_only=False, no_gate=False):
    inst = get_instance(iid)
    issue = inst["problem_statement"]
    model = "arm_b_v3_nogate" if no_gate else "arm_b_v2"   # ablation: same loop, no independent gate
    print(f"instance={iid} repo={inst['repo']} base={inst['base_commit'][:10]} "
          f"problem_chars={len(issue)} model={model}")
    if check_only:
        print("check-only OK; claude:", os.path.exists(CLAUDE), "codex:", os.path.exists(CODEX),
              "image:", TB.image_for(iid))
        return

    img = TB.ensure_image(iid)
    print(f"[v2] image ready: {img}")
    work = tempfile.mkdtemp(prefix="arm_b_v2_")
    repo = os.path.join(work, "repo")
    tid = "task_armbv2_" + iid.replace("__", "_")
    rcs, repro_outcomes, gate_log, timed = [], [], [], False
    accepted = False
    stop_reason = "budget_exhausted"
    try:
        C.prepare_clone(inst, repo)
        _ledger(lambda: K.submit_task({
            "id": tid, "schema_version": "0.1", "workspace": "logos-eval", "objective": f"fix {iid}",
            "writable_scope": ["<source>"], "acceptance": ["independent gate COMPLETE + held-out harness"],
            "output_contract": "artifact", "budget": {"tokens": None, "seconds": None, "usd": None},
            "state": "DRAFT", "protected": False, "created_by": "claude-worker", "created_at": K._now()}))
        for st, who in [("PROPOSED", "claude-architect"), ("VALIDATED", "codex"),
                        ("AUTHORIZED", "neo"), ("EXECUTING", "claude-worker")]:
            _ledger(lambda st=st, who=who: K.transition_task({"id": tid}, st, who))

        feedback, last_diff = "", None
        for step in range(1, BUDGET + 1):
            diff_so_far = C.staged_diff(repo) if step > 1 else ""
            rc, to = run_claude(repo, turn_prompt(issue, diff_so_far, feedback, step == 1))
            rcs.append(rc)
            timed = timed or to
            _ledger(lambda step=step, rc=rc: K.append_event(
                "claude-worker", "patch.proposed", {"step": step, "agent_rc": rc}, task_id=tid))
            cur_diff = C.staged_diff(repo)
            if step > 1 and cur_diff == last_diff:
                print(f"[v2] step {step}: no change since last turn -> stuck, stop")
                stop_reason = "stuck"
                break
            last_diff = cur_diff

            if not os.path.exists(os.path.join(repo, REPRO)):
                print(f"[v2] step {step}: no {REPRO} yet (agent_rc={rc}, timed_out={to})")
                feedback = f"You have not created {REPRO} yet. Create it and fix the source."
                continue

            r = TB.run_in_testbed(img, repo, f"python {REPRO}", timeout=REPRO_TIMEOUT)
            repro_outcomes.append(r["outcome"])
            _ledger(lambda step=step, r=r: K.append_event(
                "execution-feedback", "test.run",
                {"step": step, "phase": "repro", "outcome": r["outcome"], "rc": r["exit_code"]}, task_id=tid))
            src = C.filter_tests(C.staged_diff(repo, exclude=[REPRO]))

            if r["outcome"] != "pass":
                print(f"[v2] step {step}: repro -> {r['outcome']} (rc={r['exit_code']})")
                feedback = (f"Your reproduction did NOT pass (exit {r['exit_code']}, {r['outcome']}).\n"
                            f"STDOUT:\n{r['stdout']}\nSTDERR:\n{r['stderr']}")
                continue
            if not src.strip():
                print(f"[v2] step {step}: repro passes but EMPTY source diff -> keep going")
                feedback = ("Your reproduction passes but you changed NO source file. The fix must live "
                            "in the SOURCE, not the reproduction.")
                continue

            # repro passes WITH a source fix
            if no_gate:
                # ABLATION (arm_b_v3_nogate): no independent gate, no stop-on-green -> refine to full budget
                gate_log.append({"step": step, "verdict": "NO_GATE"})
                print(f"[v3-nogate] step {step}: repro pass, no gate -> keep refining (full budget)")
                feedback = ("Your reproduction passes. Make the fix as COMPLETE and comprehensive as "
                            "possible — handle every case the issue describes, in the SOURCE.")
                continue
            # -> INDEPENDENT COMPLETENESS GATE (no stop-on-green)
            verdict, missing = codex_gate(issue, src)
            gate_log.append({"step": step, "verdict": verdict, "missing": missing[:300]})
            _ledger(lambda step=step, verdict=verdict: K.append_event(
                "codex", "verify.completeness", {"step": step, "verdict": verdict}, task_id=tid))
            print(f"[v2] step {step}: repro pass + gate -> {verdict}"
                  + (f" (missing: {missing[:120]})" if verdict != "COMPLETE" else ""))
            if verdict == "COMPLETE":              # the ONLY way the loop stops as a success
                accepted = True
                stop_reason = "gate_complete"
                break
            if verdict == "ERROR":                 # FAIL-CLOSED: never accept on a gate error; keep refining
                feedback = ("An independent completeness check could not be obtained this round. Make the "
                            "fix as COMPLETE and comprehensive as possible — handle every case the issue "
                            "describes, in the SOURCE (not the reproduction).")
                continue
            feedback = (f"Your reproduction passes, but an INDEPENDENT reviewer judged the fix INCOMPLETE.\n"
                        f"WHAT IS MISSING: {missing}\n"
                        "Address the missing cases in the SOURCE (do not just edit the reproduction).")

        raw = C.staged_diff(repo)
        diff = C.filter_tests(C.staged_diff(repo, exclude=[REPRO]))
        base = C.write_prediction(
            PREDS, iid, model, diff, raw,
            {"agent_rcs": rcs, "timed_out": timed, "steps": len(rcs), "repro_outcomes": repro_outcomes,
             "gate_log": gate_log, "accepted_by_gate": accepted, "stop_reason": stop_reason, "image": img})
        _ledger(lambda: K.record_artifact({
            "id": "art_" + tid, "task_id": tid, "kind": "patch", "content_hash": K._sha({"f": diff}),
            "produced_by": "claude-worker", "produced_at": K._now(), "reality_state": "STANDALONE",
            "evidence": [f"gate:{'COMPLETE' if accepted else 'not-accepted'}", f"steps:{len(rcs)}",
                         f"patch_bytes:{len(diff)}"],
            "verification": {"tests_passed": False, "reviewed_by": ["execution-feedback", "codex"],
                             "verdict": "PENDING_OFFICIAL_SCORE"}}))
        _ledger(lambda: K.transition_task({"id": tid}, "VERIFYING", "official-harness"))
        print(f"Arm B v2 {iid}: steps={len(rcs)} gate_accepted={accepted} stop={stop_reason} "
              f"timed_out={timed} patch={len(diff)}b (raw {len(raw)}b) "
              f"gates={[g['verdict'] for g in gate_log]} -> {base}.jsonl")
    except Exception as e:  # noqa: BLE001 - salvage partial work after a clean clone
        sys.stderr.write(f"[v2] post-clone error: {e!r}; salvaging\n")
        try:
            raw = C.staged_diff(repo)
            diff = C.filter_tests(C.staged_diff(repo, exclude=[REPRO]))
            C.write_prediction(PREDS, iid, model, diff, raw,
                               {"agent_rcs": rcs, "timed_out": timed, "steps": len(rcs),
                                "repro_outcomes": repro_outcomes, "gate_log": gate_log,
                                "accepted_by_gate": accepted, "stop_reason": "error",
                                "error": repr(e), "salvaged": True})
        except Exception as e2:  # noqa: BLE001
            sys.stderr.write(f"[v2] could not salvage ({e2!r})\n")
    finally:
        subprocess.run(["rm", "-rf", work])


if __name__ == "__main__":
    iid = next((a for a in sys.argv[1:] if not a.startswith("--")), "pytest-dev__pytest-5840")
    run_arm_b_v2(iid, check_only="--check" in sys.argv, no_gate="--no-gate" in sys.argv)
