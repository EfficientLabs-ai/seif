# Governed Integration Fabric (self-hosted Composio + Nango, SEIF-governed)

Date: 2026-06-22 · Status: governance layer BUILT (`logos/capability_grant.py`); deployment TARGET (founder-gated keys).

## The goal (founder intent)
Efficient Labs users connect **any** service (Gmail, GitHub, Slack, Notion, Stripe, …) with **zero
friction**, and their agents get real work done through those services — **without ever handing the
LLM raw provider access**, and **without a third-party SaaS ever seeing their tokens.** Sovereign,
self-hosted, governed. "Give them hands without surrendering control."

## The three layers
```
USER (zero-friction connect)
   │  one-click OAuth — self-hosted on EFL infra, tokens never leave it
   ▼
NANGO (self-hosted)         — connection lifecycle: OAuth dance, token storage/refresh, per-user/tenant
   │                          isolation. Tokens live HERE (secret_location = "nango:<connector>").
   ▼
COMPOSIO (self-hosted)      — the action catalog: typed tools/actions per provider (list_issues,
   │                          create_draft_comment, send_email, …). Executes the actual API calls.
   ▼
SEIF CAPABILITY GRANTS      — the gate (logos/capability_grant.py). The agent is NEVER given the
   │  deny-by-default        connection; it is minted a SCOPED, TIME-LIMITED, RECEIPTED capability:
   ▼                         "read issues from repo X · create a draft comment · cannot merge · expires
RECEIPTS (SEIF ledger)        when the task ends." Every check is logged + replayable.
```

## Why this is the moat, not just plumbing
- **Sovereign:** tokens never touch a third-party SaaS — Nango runs on your infra.
- **Zero friction for the user:** one OAuth click; they never see scopes/keys.
- **Governed for safety:** the LLM can't escalate. `capability_grant.check()` is deny-by-default —
  ungranted action → DENY; wrong scope → DENY; expired → DENY; high/protected-risk write → DENY unless
  founder-approved. Tokens are never in the grant (only `secret_location` points at Nango).
- **Provable:** every capability check emits a receipt to the SEIF ledger.

## Connector declaration (each integration declares, before it can be used)
provider · account_owner · available_actions · read_scopes · write_scopes · secret_location (Nango) ·
rate_limits · idempotency_support · risk_class (low|medium|high|protected) · approval_requirement ·
receipt_policy. An action is callable only via a grant whose `allowed_actions`/scopes/expiry/approval permit it.

## MCP fits as the interface, not the security boundary
Composio actions are exposed to agents over **MCP** (standard tool interface). MCP is NOT a security
control — SEIF capability grants are. Every MCP tool call carries: subject · capability · task ·
authority · budget · idempotency key · receipt requirement, and SEIF (not MCP) decides allow/deny.

## Built now (no keys needed) vs founder-gated
- ✅ **BUILT:** `capability_grant.py` (mint/check/authorize, deny-by-default, scoped, expiring,
  approval-gated, receipted) + selftest/unittests.
- ⛔ **FOUNDER-GATED (deployment):** self-host Nango + Composio instances; provider OAuth app
  credentials; the secrets broker. Per directive: do NOT distribute before local correctness; this is
  P3/Wave-3 — it follows the Evidence Engine being measured.

## Next steps when greenlit
1. Stand up self-hosted Nango + Composio (founder provides OAuth app creds → vault).
2. Write connector declarations (schema above) for the first providers (GitHub, Gmail).
3. Wire the MCP action layer through `capability_grant.authorize()` (SEIF interception) + receipts.
4. EXOS surface: user sees their connections, the agent's active grants, and every capability receipt.
