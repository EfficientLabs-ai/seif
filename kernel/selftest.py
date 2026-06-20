#!/usr/bin/env python3
"""SEIF kernel self-test + adversarial regression suite (C0 fixes).
Proves the invariants hold AND that the 4 confirmed bypasses are now rejected."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import seif_kernel as K

PASS = []


def expect_reject(name, fn):
    try:
        fn()
    except K.KernelReject:
        PASS.append(name); print(f"PASS  {name} (correctly rejected)"); return
    raise SystemExit(f"FAIL  {name}: expected KernelReject, got none")


def expect_ok(name, fn):
    fn(); PASS.append(name); print(f"PASS  {name}")


def fresh():
    for p in (K.EVENTS, K.RECEIPTS, K.APPROVALS):
        if p.exists():
            p.unlink()


def task(tid, protected=False, state="DRAFT"):
    return {"id": tid, "schema_version": "0.1", "workspace": "seif", "objective": "demo",
            "writable_scope": [], "acceptance": ["selftest passes"], "output_contract": "report",
            "budget": {"tokens": None, "seconds": None, "usd": None}, "state": state,
            "protected": protected, "created_by": "claude", "created_at": K._now()}


fresh()

# --- core invariants ---
expect_reject("bad-task-envelope", lambda: K.validate("task", {"id": "x"}))

t1 = task("task_001")
expect_ok("submit-valid-task", lambda: K.submit_task(t1))
assert any(e["type"] == "task.created" for e in K._read(K.EVENTS)), "no task.created"

expect_reject("illegal-transition", lambda: K.transition_task(t1, "ACCEPTED", "claude"))
expect_ok("legal-path", lambda: (K.transition_task(t1, "PROPOSED", "claude"),
                                 K.transition_task(t1, "VALIDATED", "codex")))

t2 = task("task_prot", protected=True)
K.submit_task(t2)
K.transition_task(t2, "PROPOSED", "claude")
K.transition_task(t2, "VALIDATED", "codex")
expect_reject("protected-without-approval", lambda: K.transition_task(t2, "AUTHORIZED", "claude"))

# --- adversarial regressions (C0) ---
# F2: lying task object (protected=false) must STILL be rejected — protected is ledger truth
liar = task("task_prot", protected=False, state="VALIDATED")
expect_reject("F2-lying-task-object", lambda: K.transition_task(liar, "AUTHORIZED", "attacker"))

K.record_approval({"id": "ap_1", "action_ref": "task_prot", "protected_action": "publish_public",
                   "requested_by": "claude", "requested_at": K._now(), "status": "APPROVED",
                   "approver": "neo", "decided_at": K._now()})
expect_ok("protected-with-neo-approval", lambda: K.transition_task(t2, "AUTHORIZED", "neo"))

# F3: forged illegal transition event rejected at append time
expect_reject("F3-forged-transition",
              lambda: K.append_event("attacker", "task.transition", {"from": "PROPOSED", "to": "ACCEPTED", "guard": "x"}, task_id="task_001"))

# F4: empty-string evidence / reviewer must be rejected
expect_reject("F4-empty-evidence-claim", lambda: K.validate("claim", {
    "id": "c", "statement": "s", "reality_state": "LIVE", "truth_class": "CLAIM",
    "epistemic_status": "OBSERVED", "verification_status": "TESTED",
    "valid_time": {"from": K._now()}, "recorded_time": {"from": K._now()}, "evidence": [""], "actor": "neo"}))
expect_reject("F4-empty-reviewer-artifact", lambda: K.validate("artifact", {
    "id": "a", "task_id": "t", "kind": "patch", "content_hash": "h", "produced_by": "claude",
    "produced_at": K._now(), "reality_state": "WIRED", "evidence": ["ev1"],
    "verification": {"verdict": "ACCEPTED", "tests_passed": True, "reviewed_by": [""]}}))

# F5: global idempotency — same key on a different stream is still a duplicate
K.append_event("claude", "demo.x", idempotency_key="dup-1", stream="main")
K.append_event("claude", "demo.x", idempotency_key="dup-1", stream="sidecar")
assert [r for r in K._read(K.RECEIPTS) if r["result"] == "SKIPPED_DUPLICATE"], "global dedup failed"
PASS.append("F5-global-idempotency"); print("PASS  F5-global-idempotency")

expect_ok("hash-chain-intact", K.verify_chain)

print(f"\n{len(PASS)} invariants + regressions PASS | events={len(K._read(K.EVENTS))} receipts={len(K._read(K.RECEIPTS))} approvals={len(K._read(K.APPROVALS))}")
