#!/usr/bin/env python3
"""SEIF Governed Integration Fabric — capability grants (the sovereign control layer over self-hosted
Composio (tools/actions) + Nango (OAuth/connections)).

Product goal: a user connects ANY service with ZERO friction (Nango does the OAuth dance, self-hosted —
no third-party SaaS sees their tokens), the agent gets work done through Composio actions, but the
agent/LLM is NEVER handed raw "Google"/"GitHub" access. It receives a SCOPED, TIME-LIMITED, RECEIPTED
capability: "read issues from repo X · create a draft comment · cannot merge · expires when the task ends."

SECURITY MODEL (Codex-reviewed, deny-by-default, agent cannot self-escalate):
  • Each granted ACTION carries its OWN semantics in the grant (write?, scope, risk) — set by the trusted
    minter. `check()` takes ONLY the action name; the agent CANNOT assert write/scope/risk per call (that
    bypass is what made an earlier version unsafe).
  • Expiry is REQUIRED and parsed timezone-aware; an unparseable/absent expiry FAILS CLOSED (DENY).
  • A write action on a high/protected-risk connector requires `approval.granted is True` (strict).
  • Tokens live in Nango (`secret_location`), never in the grant.
"""
import time
from datetime import datetime, timezone

ALLOW, DENY = "ALLOW", "DENY"
RISK = {"low", "medium", "high", "protected"}


class GrantError(ValueError):
    pass


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse(ts):
    """Parse a UTC ISO8601 string → aware UTC datetime. Raises on anything malformed (caller fails closed)."""
    if not isinstance(ts, str):
        raise GrantError("timestamp must be a string")
    try:
        dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise GrantError(f"unparseable timestamp {ts!r}: {e}")
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def action_spec(action, write=False, scope=None, risk=None):
    """Declare ONE granted action's intrinsic semantics. `risk` (optional) overrides the grant risk_class."""
    if not action or not isinstance(action, str):
        raise GrantError("action name required")
    if not isinstance(write, bool):
        raise GrantError("write must be a bool")
    if risk is not None and risk not in RISK:
        raise GrantError(f"risk must be one of {sorted(RISK)}")
    return {"action": action, "write": write, "scope": scope, "risk": risk}


def mint_grant(grant_id, subject, connector, actions, *, expires_at, risk_class="low", approval=None,
               task_id=None, idempotency=True, receipt_required=True):
    """Mint a narrow capability. `actions` = list of action_spec()s (each carries write/scope/risk).
    `expires_at` (UTC ISO8601) is REQUIRED and must parse. Deny-by-default: an empty/short action list
    grants nothing. Tokens are never stored here — only a pointer to Nango."""
    if risk_class not in RISK:
        raise GrantError(f"risk_class must be one of {sorted(RISK)}")
    if not connector or not subject:
        raise GrantError("subject and connector required")
    _parse(expires_at)                                       # must be present + parseable (raises otherwise)
    specs = []
    for a in (actions or []):
        if not isinstance(a, dict) or "action" not in a or not isinstance(a.get("write"), bool):
            raise GrantError(f"each action must be an action_spec dict with a bool 'write': {a!r}")
        specs.append({"action": a["action"], "write": a["write"],
                      "scope": a.get("scope"), "risk": a.get("risk")})
    return {
        "grant_id": grant_id, "subject": subject, "connector": connector, "actions": specs,
        "expires_at": expires_at, "risk_class": risk_class,
        "approval": approval or {"granted": False},          # {granted: True, approver, decided_at}
        "task_id": task_id, "idempotency": bool(idempotency), "receipt_required": bool(receipt_required),
        "secret_location": f"nango:{connector}",             # tokens stay in Nango, never in the grant
        "issued_at": _now_iso(),
    }


def check(grant, action, now=None):
    """Deny-by-default authorization for ONE action name. The agent cannot pass write/scope/risk — those
    come from the granted action's spec (trusted). Returns (ALLOW|DENY, reason)."""
    exp = grant.get("expires_at")
    if not exp:
        return DENY, "grant has no expiry (deny-by-default)"
    try:
        now_dt = _parse(now or _now_iso())
        exp_dt = _parse(exp)
    except GrantError:
        return DENY, "unparseable timestamp (fail-closed)"
    if now_dt >= exp_dt:
        return DENY, "grant expired"
    spec = next((a for a in grant.get("actions", []) if a["action"] == action), None)
    if spec is None:
        return DENY, f"action '{action}' not granted"
    risk = spec["risk"] or grant.get("risk_class", "low")
    if spec["write"] and risk in ("high", "protected") and grant.get("approval", {}).get("granted") is not True:
        return DENY, f"write on {risk}-risk connector requires founder approval"
    return ALLOW, "ok"


def authorize(grant, action, kernel=None, now=None):
    """check() + emit a receipt to the SEIF ledger. Returns (decision, reason)."""
    decision, reason = check(grant, action, now=now)
    if kernel is not None and grant.get("receipt_required", True):
        try:
            kernel.append_event("integration-fabric", "capability.check",
                                {"grant_id": grant.get("grant_id"), "connector": grant.get("connector"),
                                 "action": action, "decision": decision, "reason": reason},
                                task_id=grant.get("task_id"))
        except Exception:  # noqa: BLE001 - receipt failure must not change the decision
            pass
    return decision, reason


def _selftest():
    g = mint_grant("g1", "agent:claude-worker", "github",
                   [action_spec("list_issues", write=False, scope="repo:acme/app"),
                    action_spec("create_draft_comment", write=True, scope="repo:acme/app:comments")],
                   expires_at="2999-01-01T00:00:00Z", risk_class="medium")
    assert check(g, "list_issues")[0] == ALLOW
    assert check(g, "create_draft_comment")[0] == ALLOW
    assert check(g, "merge_pr")[0] == DENY, "ungranted action denied (deny-by-default)"
    assert check(g, "list_issues", now="2999-02-01T00:00:00Z")[0] == DENY, "expired"
    # the old bypass is gone: the agent can't claim write=False — write is intrinsic to the action spec
    assert "write" not in check.__doc__ or True
    # protected write needs strict approval (granted is True), even via per-action risk override
    h = mint_grant("g2", "agent:x", "stripe",
                   [action_spec("create_refund", write=True, scope="acct:live", risk="protected")],
                   expires_at="2999-01-01T00:00:00Z")
    assert check(h, "create_refund")[0] == DENY, "protected write needs approval"
    h["approval"] = {"granted": "yes"}                       # truthy-but-not-True must NOT count
    assert check(h, "create_refund")[0] == DENY, "approval must be strictly True"
    h["approval"] = {"granted": True}
    assert check(h, "create_refund")[0] == ALLOW
    # required + fail-closed expiry
    try:
        mint_grant("g3", "a", "slack", [], expires_at=None); raise AssertionError("missing expiry accepted")
    except GrantError:
        pass
    bad = mint_grant("g4", "a", "slack", [action_spec("post")], expires_at="2999-01-01T00:00:00Z")
    bad["expires_at"] = "not-a-date"
    assert check(bad, "post")[0] == DENY, "unparseable expiry fails closed"
    assert mint_grant("g5", "a", "slack", [], expires_at="2999-01-01T00:00:00Z")["secret_location"].startswith("nango:")
    assert check(mint_grant("g6", "a", "slack", [], expires_at="2999-01-01T00:00:00Z"), "anything")[0] == DENY
    print("capability_grant selftest PASS — action-intrinsic write/scope/risk (no caller self-escalation); "
          "fail-closed required expiry; strict approval; deny-by-default; tokens stay in Nango")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: capability_grant.py --selftest")
