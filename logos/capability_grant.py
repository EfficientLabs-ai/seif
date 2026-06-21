#!/usr/bin/env python3
"""SEIF Governed Integration Fabric — capability grants (the sovereign control layer over self-hosted
Composio (tools/actions) + Nango (OAuth/connections)).

The product goal: a user connects ANY service with ZERO friction (Nango handles the OAuth dance,
self-hosted on your infra — no third-party SaaS sees their tokens), and the agent gets WORK DONE through
Composio actions — but the agent/LLM is NEVER handed raw "Google"/"GitHub" access. It receives a SCOPED,
TIME-LIMITED, RECEIPTED capability such as: "read issues from repo X · create a draft comment · cannot
merge · expires when the task ends." This module is the deny-by-default gate that enforces exactly that.

Deployment of the Composio/Nango instances + secrets is founder-gated; this governance layer is the part
that makes the fabric sovereign and safe, and it is buildable + testable without any keys.
"""
import time

ALLOW, DENY = "ALLOW", "DENY"
RISK = {"low", "medium", "high", "protected"}


class GrantError(ValueError):
    pass


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def mint_grant(grant_id, subject, connector, allowed_actions, *, read_scopes=None, write_scopes=None,
               expires_at=None, risk_class="low", approval=None, task_id=None, idempotency=True,
               receipt_required=True):
    """Mint a narrow capability. `expires_at` is a UTC ISO8601 string (lexically comparable). A grant with
    no allowed_actions denies everything (deny-by-default). High/protected risk + any write require an
    explicit approval record. Tokens live in Nango (secret_location), never in the grant."""
    if risk_class not in RISK:
        raise GrantError(f"risk_class must be one of {sorted(RISK)}")
    if not connector or not subject:
        raise GrantError("subject and connector required")
    return {
        "grant_id": grant_id, "subject": subject, "connector": connector,
        "allowed_actions": list(allowed_actions or []),
        "read_scopes": list(read_scopes or []), "write_scopes": list(write_scopes or []),
        "expires_at": expires_at, "risk_class": risk_class,
        "approval": approval or {"granted": False},          # {granted, approver, decided_at}
        "task_id": task_id, "idempotency": bool(idempotency), "receipt_required": bool(receipt_required),
        "secret_location": f"nango:{connector}",             # tokens stay in Nango, never in the grant
        "issued_at": _now_iso(),
    }


def check(grant, action, *, scope=None, write=False, now=None):
    """Deny-by-default authorization for one (action, scope, write?) against a grant. Returns (ALLOW|DENY, reason)."""
    now = now or _now_iso()
    if grant.get("expires_at") and now >= grant["expires_at"]:
        return DENY, "grant expired"
    if action not in grant.get("allowed_actions", []):
        return DENY, f"action '{action}' not granted"
    if write:
        if grant.get("risk_class") in ("high", "protected") and not grant.get("approval", {}).get("granted"):
            return DENY, f"write on {grant['risk_class']}-risk connector requires founder approval"
        if scope is not None and scope not in grant.get("write_scopes", []):
            return DENY, f"write scope '{scope}' not granted"
    else:
        allowed = set(grant.get("read_scopes", [])) | set(grant.get("write_scopes", []))
        if scope is not None and scope not in allowed:
            return DENY, f"read scope '{scope}' not granted"
    return ALLOW, "ok"


def authorize(grant, action, kernel=None, *, scope=None, write=False, now=None):
    """check() + emit a receipt to the SEIF ledger (receipt_required by default). Returns (decision, reason)."""
    decision, reason = check(grant, action, scope=scope, write=write, now=now)
    if kernel is not None and grant.get("receipt_required", True):
        try:
            kernel.append_event("integration-fabric", "capability.check",
                                {"grant_id": grant.get("grant_id"), "connector": grant.get("connector"),
                                 "action": action, "scope": scope, "write": write,
                                 "decision": decision, "reason": reason}, task_id=grant.get("task_id"))
        except Exception:  # noqa: BLE001 - receipt failure must not change the decision
            pass
    return decision, reason


def _selftest():
    g = mint_grant("g1", subject="agent:claude-worker", connector="github",
                   allowed_actions=["list_issues", "create_draft_comment"],
                   read_scopes=["repo:acme/app"], write_scopes=["repo:acme/app:comments"],
                   expires_at="2999-01-01T00:00:00Z", risk_class="medium")
    assert check(g, "list_issues", scope="repo:acme/app")[0] == ALLOW
    assert check(g, "merge_pr")[0] == DENY, "ungranted action must be denied (deny-by-default)"
    assert check(g, "create_draft_comment", scope="repo:acme/app:comments", write=True)[0] == ALLOW
    assert check(g, "create_draft_comment", scope="repo:other:comments", write=True)[0] == DENY, "wrong write scope"
    assert check(g, "list_issues", scope="repo:acme/app", now="2999-02-01T00:00:00Z")[0] == DENY, "expired"
    # high-risk write needs approval
    h = mint_grant("g2", "agent:x", "stripe", ["create_refund"], write_scopes=["acct:live"], risk_class="protected")
    assert check(h, "create_refund", scope="acct:live", write=True)[0] == DENY, "protected write needs approval"
    h["approval"] = {"granted": True, "approver": "neo", "decided_at": _now_iso()}
    assert check(h, "create_refund", scope="acct:live", write=True)[0] == ALLOW, "approved -> allow"
    # empty grant denies everything
    empty = mint_grant("g3", "agent:x", "slack", [])
    assert check(empty, "post_message")[0] == DENY
    # tokens never live in the grant
    assert "token" not in str(g).lower() and g["secret_location"].startswith("nango:")
    print("capability_grant selftest PASS — deny-by-default; scoped read/write; expiry; protected-write "
          "needs approval; tokens stay in Nango (never in the grant)")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: capability_grant.py --selftest")
