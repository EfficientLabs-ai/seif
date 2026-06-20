#!/usr/bin/env python3
"""SEIF kernel self-test — proves the invariants hold (MEASURED, not asserted)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import seif_kernel as K

PASS = []


def expect_reject(name, fn):
    try:
        fn()
    except K.KernelReject:
        PASS.append(name)
        print(f"PASS  {name} (correctly rejected)")
        return
    raise SystemExit(f"FAIL  {name}: expected KernelReject, got none")


def expect_ok(name, fn):
    fn()
    PASS.append(name)
    print(f"PASS  {name}")


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

# 1. malformed envelope rejected
expect_reject("bad-task-envelope", lambda: K.validate("task", {"id": "x"}))

# 2. valid task submits and emits an event
t1 = task("task_001")
expect_ok("submit-valid-task", lambda: K.submit_task(t1))
assert any(e["type"] == "task.created" for e in K._read(K.EVENTS)), "no task.created event"

# 3. illegal transition rejected
expect_reject("illegal-transition", lambda: K.transition_task(task("task_x", state="DRAFT"), "ACCEPTED", "claude"))

# 4. legal path DRAFT->PROPOSED->VALIDATED
expect_ok("legal-path", lambda: (K.transition_task(t1, "PROPOSED", "claude"),
                                 K.transition_task(t1, "VALIDATED", "codex")))

# 5. protected task cannot reach AUTHORIZED without neo approval...
t2 = task("task_prot", protected=True, state="VALIDATED")
expect_reject("protected-without-approval", lambda: K.transition_task(t2, "AUTHORIZED", "claude"))
# ...then succeeds with an APPROVED-by-neo approval
K.record_approval({"id": "ap_1", "action_ref": "task_prot", "protected_action": "publish_public",
                   "requested_by": "claude", "requested_at": K._now(), "status": "APPROVED",
                   "approver": "neo", "decided_at": K._now()})
expect_ok("protected-with-neo-approval", lambda: K.transition_task(t2, "AUTHORIZED", "neo"))

# 6. idempotency: same key twice -> second is a SKIPPED_DUPLICATE
K.append_event("claude", "demo.x", idempotency_key="dup-key-1")
K.append_event("claude", "demo.x", idempotency_key="dup-key-1")
dups = [r for r in K._read(K.RECEIPTS) if r["result"] == "SKIPPED_DUPLICATE"]
assert dups, "idempotency dedup did not fire"
PASS.append("idempotency-dedup")
print("PASS  idempotency-dedup")

# 7. hash chain integrity
expect_ok("hash-chain-intact", K.verify_chain)

print(f"\n{len(PASS)}/8 invariants PASS | events={len(K._read(K.EVENTS))} receipts={len(K._read(K.RECEIPTS))} approvals={len(K._read(K.APPROVALS))}")
