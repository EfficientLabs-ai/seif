#!/usr/bin/env python3
"""SEIF v0.1 microkernel (reference implementation).

Enforces the 7 kernel functions over a local append-only JSONL ledger, using the
Phase-2 contracts (schemas/) + governance (FSM + protected-action matrix). A LIBRARY
the agents call, not a service. No network, no secrets.

Security model (see THREAT_MODEL.md): all security decisions are derived from the
LEDGER, never from caller-supplied objects. Cryptographic authenticity (per-event
signatures) is NOT_IN_V0_1 — today's guarantees assume mutations go through this API
and ledger/ is protected by OS perms. Hardened against adversarial-verify C0 (2026-06-20).
"""
import json
import hashlib
import time
import datetime
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SEIF = Path(__file__).resolve().parent.parent
SCHEMAS, GOV, LEDGER = SEIF / "schemas", SEIF / "governance", SEIF / "ledger"
LEDGER.mkdir(exist_ok=True)
EVENTS, RECEIPTS, APPROVALS = LEDGER / "events.jsonl", LEDGER / "receipts.jsonl", LEDGER / "approvals.jsonl"

_VALIDATORS = {n: Draft202012Validator(json.load(open(SCHEMAS / f"{n}.schema.json")))
               for n in ["task", "event", "artifact", "claim", "decision", "approval", "receipt"]}
_FSM = yaml.safe_load(open(GOV / "workflow_transitions.yaml"))
_PROTECTED = {a["id"] for a in yaml.safe_load(open(GOV / "protected_actions.yaml"))["actions"]}


class KernelReject(Exception):
    """Deterministic rejection — the symbolic layer saying no. Never a neural decision."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read(p):
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


# --- fn 2: validate typed envelopes ---------------------------------------
def validate(kind, obj):
    errs = sorted(_VALIDATORS[kind].iter_errors(obj), key=str)
    if errs:
        raise KernelReject(f"{kind} invalid: {errs[0].message}")
    return True


# --- fn 4: legal state transitions ----------------------------------------
def legal_transition(frm, to):
    for t in _FSM["transitions"]:
        if (t["from"] == frm or t["from"] == "*") and t["to"] == to:
            return t["guard"]
    raise KernelReject(f"illegal transition {frm}->{to}")


# --- fn 5: append immutable events + receipts -----------------------------
def _last_event(stream):
    last = None
    for e in _read(EVENTS):
        if e.get("stream", "main") == stream:
            last = e
    return last


def append_event(actor, etype, payload=None, task_id=None, idempotency_key=None, stream="main"):
    payload = payload or {}
    # F3 fix: a transition event in the log must itself be a legal FSM edge.
    if etype == "task.transition":
        legal_transition(payload.get("from"), payload.get("to"))
    # F5 fix: idempotency is GLOBAL (a dedup token holds across all streams).
    if idempotency_key:
        for e in _read(EVENTS):
            if e.get("idempotency_key") == idempotency_key:
                write_receipt(actor, f"event:{etype}", "SKIPPED_DUPLICATE", idempotency_key, duplicate_of=e["id"])
                return e
    prev = _last_event(stream)
    seq = (prev["seq"] + 1) if prev else 0
    ev = {"id": f"event_{stream}_{seq:06d}", "ts": _now(), "actor": actor, "type": etype,
          "task_id": task_id, "payload": payload, "stream": stream, "seq": seq,
          "idempotency_key": idempotency_key, "retry_of": None,
          "prev_hash": prev["hash"] if prev else None, "signature": None}
    ev["hash"] = _sha({k: v for k, v in ev.items() if k not in ("hash", "signature")})
    validate("event", ev)
    with open(EVENTS, "a") as f:
        f.write(json.dumps(ev) + "\n")
    return ev


def write_receipt(actor, action, result, idempotency_key, inputs_hash=None,
                  output_hash=None, failure_reason=None, duplicate_of=None):
    r = {"id": f"receipt_{int(time.time() * 1000000)}", "action": action, "actor": actor, "ts": _now(),
         "task_id": None, "event_id": None, "result": result, "idempotency_key": idempotency_key,
         "inputs_hash": inputs_hash or _sha({"a": action}), "output_hash": output_hash,
         "failure_reason": failure_reason, "duplicate_of": duplicate_of, "sig_alg": "sha256", "signature": None}
    validate("receipt", r)
    with open(RECEIPTS, "a") as f:
        f.write(json.dumps(r) + "\n")
    return r


# --- fn 1/6: protected-action gate (LEDGER-derived, never caller-derived) --
def is_protected(action_id):
    return action_id in _PROTECTED


def _approval_for(action_ref):
    appr = None
    for a in _read(APPROVALS):
        if a["action_ref"] == action_ref:
            appr = a
    return appr


def record_approval(approval):
    validate("approval", approval)
    if approval["protected_action"] not in _PROTECTED:
        raise KernelReject(f"unknown protected_action {approval['protected_action']}")
    with open(APPROVALS, "a") as f:
        f.write(json.dumps(approval) + "\n")
    append_event(approval.get("approver") or approval["requested_by"],
                 "approval.granted" if approval["status"] == "APPROVED" else "approval.requested",
                 {"protected_action": approval["protected_action"], "status": approval["status"]},
                 task_id=approval["action_ref"])
    return approval


# --- state is a PROJECTION of the event log, not a caller's claim ----------
def project_task(task_id):
    created, state, protected = None, None, False
    for e in _read(EVENTS):
        if e.get("task_id") != task_id:
            continue
        if e["type"] == "task.created":
            created, state, protected = e, "DRAFT", bool(e["payload"].get("protected"))
        elif e["type"] == "task.transition" and state is not None:
            if e["payload"].get("from") != state:
                raise KernelReject(f"ledger inconsistency for {task_id}: from={e['payload'].get('from')} but state={state}")
            state = e["payload"]["to"]
    return {"id": task_id, "exists": created is not None, "state": state, "protected": protected}


# --- orchestration: task lifecycle ----------------------------------------
def submit_task(task):
    validate("task", task)
    if task["state"] != "DRAFT":
        raise KernelReject("new task must start in DRAFT")
    if project_task(task["id"])["exists"]:
        raise KernelReject(f"task {task['id']} already exists")
    # F2 fix: protected status is recorded in the ledger so it can't be lied about later.
    append_event(task["created_by"], "task.created",
                 {"objective": task["objective"], "protected": bool(task.get("protected"))},
                 task_id=task["id"])
    return task


def transition_task(task, to, actor):
    tid = task["id"]
    proj = project_task(tid)                       # F2/F3 fix: derive truth from ledger
    if not proj["exists"]:
        raise KernelReject(f"task {tid} not in ledger")
    guard = legal_transition(proj["state"], to)
    if to == "AUTHORIZED" and proj["protected"]:
        a = _approval_for(tid)
        if not (a and a["status"] == "APPROVED" and a.get("approver") == "neo"):
            raise KernelReject(f"protected task {tid} requires APPROVED approval by neo")
    append_event(actor, "task.transition", {"from": proj["state"], "to": to, "guard": guard}, task_id=tid)
    write_receipt(actor, f"transition:{proj['state']}->{to}", "SUCCESS", idempotency_key=f"{tid}:{to}")
    task["state"] = to                             # convenience only; ledger is authoritative
    return task


# --- fn 5 integrity: verify the hash chain --------------------------------
def verify_chain(stream="main"):
    prev, seen = None, set()
    for e in _read(EVENTS):
        if e.get("stream", "main") != stream:
            continue
        if e["hash"] != _sha({k: v for k, v in e.items() if k not in ("hash", "signature")}):
            raise KernelReject(f"hash mismatch at {e['id']}")
        if e["prev_hash"] != (prev["hash"] if prev else None):
            raise KernelReject(f"chain break at {e['id']}")
        if prev and e["seq"] != prev["seq"] + 1:    # F1 partial: seq monotonic, no gaps/reorder
            raise KernelReject(f"seq gap/reorder at {e['id']}")
        if e["seq"] in seen:
            raise KernelReject(f"duplicate seq {e['seq']}")
        seen.add(e["seq"])
        prev = e
    return True


if __name__ == "__main__":
    print("SEIF kernel v0.1 — import me. Run kernel/selftest.py to prove invariants.")
