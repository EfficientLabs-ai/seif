#!/usr/bin/env python3
"""SEIF MCP Telemetry & Tool Profile (v0.2 WP-H). MCP is the standard INTERFACE for tools/data — it is
NOT the security boundary. SEIF is: every MCP tool call passes through `intercept()`, which authorizes it
against a capability grant (deny-by-default) and emits a receipt. SEIF — not MCP — decides allow/deny.

Two faces:
  • Typed TELEMETRY resources the runtime exposes (compile/test results, coverage/AST/fs diffs, resource
    usage, sandbox state, receipts) — typed so downstream consumers parse, not scrape.
  • A tool-call ENVELOPE every action must carry (actor, capability, task, authority, budget,
    policy_version, idempotency_key, receipt_required) — checked by SEIF before the tool runs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capability_grant as CG   # noqa: E402

ALLOW, DENY = CG.ALLOW, CG.DENY

# typed telemetry resource kinds -> required fields (consumers get structure, not scraped text)
TELEMETRY_RESOURCES = {
    "compile_result": {"ok", "stdout_tail"},
    "test_result": {"outcome", "exit_code"},
    "coverage_delta": {"added", "removed"},
    "resource_usage": {"cpu_s", "mem_mb", "duration_s"},
    "fs_diff": {"changed_files"},
    "ast_diff": {"symbols_changed"},
    "dep_change": {"added", "removed"},
    "sandbox_state": {"image", "network"},
    "receipt": {"h"},
}
# tools exposed to agents (executed only after SEIF authorizes the envelope)
TOOLS = {"run_test", "run_analysis", "apply_patch", "inspect_symbol", "request_context", "request_candidate"}
ENVELOPE_FIELDS = ("actor", "action", "capability", "task", "authority", "budget",
                   "policy_version", "idempotency_key", "receipt_required")


class ProfileError(ValueError):
    pass


def make_envelope(actor, action, capability, task, *, authority="delegated", budget=None,
                  policy_version="0.2", idempotency_key=None, receipt_required=True):
    return {"actor": actor, "action": action, "capability": capability, "task": task,
            "authority": authority, "budget": budget or {}, "policy_version": policy_version,
            "idempotency_key": idempotency_key or f"{task}:{action}", "receipt_required": receipt_required}


def validate_telemetry(kind, payload):
    if kind not in TELEMETRY_RESOURCES:
        raise ProfileError(f"unknown telemetry kind {kind!r}")
    missing = TELEMETRY_RESOURCES[kind] - set(payload or {})
    if missing:
        raise ProfileError(f"{kind} telemetry missing {sorted(missing)}")
    return True


def intercept(envelope, grant, kernel=None, now=None):
    """SEIF authorizes one MCP tool call. Deny-by-default: a malformed envelope, a capability that doesn't
    match the grant, or an action the grant doesn't permit -> DENY. Emits a receipt. Returns (decision, reason)."""
    missing = [f for f in ENVELOPE_FIELDS if f not in envelope or envelope[f] in (None, "")]
    if missing:
        return DENY, f"envelope missing {missing}"
    if envelope["action"] not in TOOLS:
        return DENY, f"unknown tool {envelope['action']!r}"
    if envelope["capability"] != grant.get("grant_id"):
        return DENY, "capability does not match the presented grant"
    if envelope.get("task") != grant.get("task_id") and grant.get("task_id") is not None:
        return DENY, "envelope task does not match the grant's task scope"
    decision, reason = CG.check(grant, envelope["action"], now=now)
    if kernel is not None and envelope.get("receipt_required", True):
        try:
            kernel.append_event("mcp-profile", "tool.intercept",
                                {"actor": envelope["actor"], "action": envelope["action"],
                                 "grant_id": grant.get("grant_id"), "decision": decision, "reason": reason,
                                 "idempotency_key": envelope["idempotency_key"]}, task_id=envelope["task"])
        except Exception:  # noqa: BLE001
            pass
    return decision, reason


def _selftest():
    g = CG.mint_grant("grantX", "agent:worker", "repo-tools",
                      [CG.action_spec("run_test", write=False), CG.action_spec("apply_patch", write=True)],
                      expires_at="2999-01-01T00:00:00Z", risk_class="low", task_id="task42")
    env = make_envelope("agent:worker", "run_test", "grantX", "task42")
    assert intercept(env, g)[0] == ALLOW, "granted tool on matching grant/task -> ALLOW"
    # ungranted tool denied (deny-by-default via the capability)
    assert intercept(make_envelope("agent:worker", "request_candidate", "grantX", "task42"), g)[0] == DENY
    # capability/grant mismatch denied
    assert intercept(make_envelope("agent:worker", "run_test", "WRONG", "task42"), g)[0] == DENY
    # task-scope mismatch denied
    assert intercept(make_envelope("agent:worker", "run_test", "grantX", "other_task"), g)[0] == DENY
    # malformed envelope denied
    bad = make_envelope("a", "run_test", "grantX", "task42"); del bad["policy_version"]
    assert intercept(bad, g)[0] == DENY, "missing envelope field -> DENY"
    # unknown tool denied
    assert intercept(make_envelope("a", "rm_rf", "grantX", "task42"), g)[0] == DENY
    # telemetry typing
    assert validate_telemetry("test_result", {"outcome": "pass", "exit_code": 0})
    try:
        validate_telemetry("test_result", {"outcome": "pass"}); raise AssertionError("missing field accepted")
    except ProfileError:
        pass
    print("mcp_profile selftest PASS — SEIF (not MCP) authorizes every tool call via the capability grant; "
          "deny-by-default on bad envelope / wrong capability / wrong task / ungranted tool; typed telemetry")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: mcp_profile.py --selftest")
