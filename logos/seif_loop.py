#!/usr/bin/env python3
"""SEIF Loop Orchestrator — the executable binding of /loop and /goal to the SEIF gate.

This is the engine the founder is removed FROM (not the gate they stay AT). It drives a backlog (or a
single goal) through the proven `/seif` flow — clean-room → real tests → integrity guard → branch/PR →
receipt — while:
  • pulling MEMORY context per task (L2 prior lessons for this task_id; L3 blast-radius of the patch),
  • recording a typed TRAJECTORY SUMMARY to episodic memory after every attempt (the "never forgets" loop),
  • enforcing CAPS (max tasks/cycle, per-task budget, timeout) and an ACCEPT-RATE FLOOR (bail early if the
    loop is failing, instead of burning the whole backlog — the anti-Ralph-Wiggum guard), and
  • QUEUEING every landed PR for founder+Codex review. It NEVER merges. Merge/secrets/production stay the
    founder's gate. ACCEPTED here means "tests passed + integrity clean", proven by a receipt — not "merged".

Gate = the project's real test suite (exit code) + the integrity guard, both inside `seif_run`. State =
Tripartite Memory + receipts. Stop = caps + accept-rate floor + (always) the founder at the merge gate.

The runner is INJECTABLE (`runner=`) so the control logic is testable with no LLM/network (see _selftest).
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "memory"))

import seif_run                              # noqa: E402
import integrity_guard as IG                # noqa: E402
import trajectory_summary as TS             # noqa: E402
from tripartite import Memory               # noqa: E402

FOUNDER_QUEUE = os.path.join(os.path.dirname(_HERE), "kernel", "ledger", "founder_queue.jsonl")

# reasons -> trajectory_summary termination vocabulary
_TERM = {"verified": "accepted", "tests": "rejected", "integrity_violation": "rejected",
         "no_change": "stuck", "error": "error"}


class LoopConfig:
    """Caps + stop conditions. Defaults are conservative for hands-off running."""

    def __init__(self, max_tasks=5, budget_per_task=3, timeout=600, make_pr=True,
                 min_accept_rate=0.0, floor_after=3):
        self.max_tasks = max_tasks
        self.budget_per_task = budget_per_task
        self.timeout = timeout
        self.make_pr = make_pr
        self.min_accept_rate = min_accept_rate   # 0.0 = never bail on rate; e.g. 0.34 = bail if <34%
        self.floor_after = floor_after           # only enforce the floor after this many attempts


def _blast_radius(mem, repo, patch):
    """Best-effort L3 context: the files the patch touched and what DEPENDS ON them (impact closure)."""
    try:
        changed = sorted(IG.changed_files(patch or ""))
        g = mem.graph(repo)
        if not g.available:
            return {"changed": changed, "impacted": None, "graph": "absent"}
        impacted = sorted({f for c in changed for f in g.impact(c)})
        return {"changed": changed, "impacted": impacted, "graph_stale": g.is_stale()}
    except Exception as e:  # noqa: BLE001  — context is advisory, never break the loop
        return {"changed": [], "impacted": None, "error": repr(e)}


def _summary_for(task, result, blast, latency_s, idx):
    reason = result.get("reason") or ("verified" if result.get("accepted") else "tests")
    term = _TERM.get(reason, "rejected")
    accepted = bool(result.get("accepted"))
    prohibited = []
    if reason == "integrity_violation":
        prohibited = ["integrity_violation: edited a protected/test surface"]
    return TS.build_summary(
        attempt_id=f"{task['task_id']}#{idx}", task_id=task["task_id"], hypothesis=task["task"][:200],
        termination_reason=term,
        localization=", ".join((blast.get("changed") or [])[:8]),
        files_changed=blast.get("changed") or [],
        evidence_passed=["project-tests", "integrity-guard"] if accepted else [],
        evidence_failed=([] if accepted else (["integrity-guard"] if reason == "integrity_violation"
                                              else ["project-tests"])),
        cost={"budget": task.get("budget")}, latency_s=latency_s,
        reusable_lesson_candidate=(task.get("lesson") or "") if accepted else "",
        prohibited_reuse_reasons=prohibited,
    )


def _queue_for_founder(record, queue_path=None):
    queue_path = queue_path or FOUNDER_QUEUE   # resolved at call time so tests can redirect it
    os.makedirs(os.path.dirname(queue_path), exist_ok=True)
    with open(queue_path, "a") as f:
        f.write(json.dumps(record) + "\n")


def run_one(task, mem, cfg, runner=None, idx=0):
    """Run ONE task through the gate. `task` = {task_id, repo, task, test_cmd, [budget], [protected], [lesson]}.
    Returns a per-task record; records a trajectory summary; queues a landed PR for the founder."""
    runner = runner or seif_run.seif_run
    repo, prompt, test_cmd = task["repo"], task["task"], task["test_cmd"]
    budget = task.get("budget", cfg.budget_per_task)
    prior = mem.episodic.query(task_id=task["task_id"], limit=3)  # what was tried before (context)
    kw = {"budget": budget, "timeout": cfg.timeout, "make_pr": cfg.make_pr}
    if "protected" in task:
        kw["protected"] = task["protected"]
    t0 = time.time()
    try:
        result = runner(repo, prompt, test_cmd, **kw)
    except Exception as e:  # noqa: BLE001  — one task's failure must not kill the cycle
        result = {"accepted": False, "reason": "error", "error": repr(e), "patch": ""}
    latency = round(time.time() - t0, 1)

    blast = _blast_radius(mem, repo, result.get("patch", ""))
    summary = _summary_for(task, result, blast, latency, idx)
    mem.record_attempt(summary)

    rec = {"task_id": task["task_id"], "repo": os.path.basename(repo.rstrip("/")),
           "accepted": bool(result.get("accepted")), "reason": result.get("reason"),
           "landed": bool(result.get("landed")), "pr": result.get("pr"),
           "receipt": (result.get("receipt") or {}).get("h"), "blast_radius": blast,
           "prior_attempts": len(prior), "latency_s": latency}
    if rec["landed"]:
        _queue_for_founder({**rec, "queued_at": summary and time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "action": "review+merge (founder gate)"})
    return rec


def run_loop(backlog, mem=None, cfg=None, runner=None):
    """Drive a backlog through the gate with caps + an accept-rate floor. Returns a cycle summary.
    `backlog` = list of task dicts. Stops at max_tasks, or early if the accept-rate floor is breached."""
    mem = mem or Memory()
    cfg = cfg or LoopConfig()
    records, accepted = [], 0
    stopped = "completed"
    tasks = backlog[:cfg.max_tasks]
    for i, task in enumerate(tasks):
        rec = run_one(task, mem, cfg, runner=runner, idx=i)
        records.append(rec)
        accepted += 1 if rec["accepted"] else 0
        done = i + 1
        rate = accepted / done
        print(f"[loop] {done}/{len(tasks)} task={task['task_id']} -> "
              f"{'ACCEPTED' if rec['accepted'] else 'rejected(' + str(rec['reason']) + ')'} "
              f"| accept_rate={rate:.0%}")
        if cfg.min_accept_rate > 0 and done >= cfg.floor_after and rate < cfg.min_accept_rate:
            stopped = f"accept_rate_floor ({rate:.0%} < {cfg.min_accept_rate:.0%} after {done})"
            print(f"[loop] STOP — {stopped}. Not burning the rest of the backlog.")
            break
    n = len(records)
    return {"attempted": n, "accepted": accepted, "landed": sum(r["landed"] for r in records),
            "accept_rate": (accepted / n) if n else 0.0, "stopped_reason": stopped,
            "backlog_size": len(backlog), "skipped": max(0, len(backlog) - n), "records": records}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="SEIF loop: drive a backlog JSON through the SEIF gate.")
    ap.add_argument("--backlog", required=True, help="path to a JSON list of task dicts")
    ap.add_argument("--max-tasks", type=int, default=5)
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--min-accept-rate", type=float, default=0.0)
    ap.add_argument("--no-pr", action="store_true")
    a = ap.parse_args()
    backlog = json.load(open(a.backlog))
    cfg = LoopConfig(max_tasks=a.max_tasks, budget_per_task=a.budget, timeout=a.timeout,
                     make_pr=not a.no_pr, min_accept_rate=a.min_accept_rate)
    out = run_loop(backlog, cfg=cfg)
    print("\n=== cycle summary ===")
    print(json.dumps({k: v for k, v in out.items() if k != "records"}, indent=2))
    sys.exit(0)


# ----------------------------------------------------------------------------- selftest
def _selftest():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="seif-loop-")
    try:
        from tripartite import Memory as Mem
        mem = Mem()
        mem.episodic.path = os.path.join(tmp, "ep.jsonl")
        mem.working.path = os.path.join(tmp, "w.json")
        qpath = os.path.join(tmp, "queue.jsonl")

        # a FAKE runner: deterministic outcome by task_id, no LLM/network
        def fake_runner(repo, prompt, test_cmd, budget=3, timeout=600, make_pr=True, protected=None):
            kind = prompt  # we encode the desired outcome in the task text for the test
            if kind == "ACCEPT":
                return {"accepted": True, "reason": "verified", "landed": True, "pr": "http://pr/1",
                        "receipt": {"h": "abc"}, "patch": "diff --git a/src.py b/src.py\n+x"}
            if kind == "INTEGRITY":
                return {"accepted": False, "reason": "integrity_violation", "patch": "",
                        "integrity": {"hard": [{"file": "test_x.py"}]}, "receipt": {"h": "def"}}
            if kind == "BOOM":
                raise RuntimeError("runner blew up")
            return {"accepted": False, "reason": "tests", "patch": "", "receipt": {"h": "ghi"}}

        # redirect the founder queue to a temp path (this module's global, resolved at call time)
        orig_q = globals()["FOUNDER_QUEUE"]
        globals()["FOUNDER_QUEUE"] = qpath
        try:
            # 1) a single accepted task records a reusable lesson + queues a PR for the founder
            cfg = LoopConfig(max_tasks=10)
            r = run_loop([{"task_id": "t_ok", "repo": tmp, "task": "ACCEPT", "test_cmd": "x",
                           "lesson": "resolve paths first"}], mem=mem, cfg=cfg, runner=fake_runner)
            assert r["accepted"] == 1 and r["landed"] == 1 and r["stopped_reason"] == "completed", r
            assert os.path.exists(qpath), "landed PR must be queued for the founder"
            assert mem.episodic.reusable_lessons(), "accepted+lesson -> reusable episode"

            # 2) integrity violation is NOT accepted, NOT queued, but IS recorded (with prohibition)
            r2 = run_loop([{"task_id": "t_bad", "repo": tmp, "task": "INTEGRITY", "test_cmd": "x"}],
                          mem=mem, cfg=cfg, runner=fake_runner)
            assert r2["accepted"] == 0 and r2["landed"] == 0, r2
            bad = mem.episodic.query(task_id="t_bad")[0]["summary"]
            assert bad["termination_reason"] == "rejected" and bad["prohibited_reuse_reasons"], bad

            # 3) a throwing runner is contained (recorded as error), loop keeps going
            r3 = run_loop([{"task_id": "t_boom", "repo": tmp, "task": "BOOM", "test_cmd": "x"},
                           {"task_id": "t_ok2", "repo": tmp, "task": "ACCEPT", "test_cmd": "x"}],
                          mem=mem, cfg=cfg, runner=fake_runner)
            assert r3["attempted"] == 2 and r3["accepted"] == 1, r3

            # 4) accept-rate floor bails early instead of burning the whole backlog
            fail4 = [{"task_id": f"f{i}", "repo": tmp, "task": "FAIL", "test_cmd": "x"} for i in range(8)]
            cfg2 = LoopConfig(max_tasks=8, min_accept_rate=0.5, floor_after=3)
            r4 = run_loop(fail4, mem=mem, cfg=cfg2, runner=fake_runner)
            assert r4["attempted"] == 3 and "accept_rate_floor" in r4["stopped_reason"], r4
            assert r4["skipped"] == 5, r4

            # 5) max_tasks cap truncates the backlog
            cfg3 = LoopConfig(max_tasks=2)
            r5 = run_loop(fail4, mem=mem, cfg=cfg3, runner=fake_runner)
            assert r5["attempted"] == 2 and r5["skipped"] == 6, r5
        finally:
            globals()["FOUNDER_QUEUE"] = orig_q

        print("seif_loop selftest PASS")
        print("  accepted->queued+lesson · integrity->rejected+recorded · throw->contained · "
              "floor->early-stop · cap->truncate")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
