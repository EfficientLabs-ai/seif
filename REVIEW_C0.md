# SEIF v0.1 Phase 2 — Contract Review (round C0)

## Auditors
- **Codex** (`gpt-5.3-codex-spark`, xhigh) — full review delivered.
- **Gemini** — **quota-blocked**: free tier is `gemini-3.5-flash`, 20 requests/day, exhausted this session (`TerminalQuotaError`). Re-review deferred until quota resets OR a billed `GEMINI_API_KEY` is added. This round was **single-auditor** — stated honestly, not inflated.

## Accepted + APPLIED (with measured proof)
1. **Evidence-first now enforced (was only documented).** `claim`: `truth_class=CLAIM` ⇒ `evidence` minItems 1 AND `verification_status` ≠ UNVERIFIED. `artifact`: `verdict=ACCEPTED` ⇒ `tests_passed=true` + ≥1 `reviewed_by` + ≥1 `evidence`. **Proven:** empty-evidence CLAIM and unverified ACCEPTED are rejected by the validator.
2. **Approval gate hardened.** Added `expires_at` (fixes dead EXPIRED state); `protected_action` constrained to the 10-id enum; `status=APPROVED` ⇒ `approver=neo` + `decided_at`. **Proven:** non-neo APPROVED is rejected.
3. **Event integrity.** Added `stream` + monotonic `seq` + `retry_of`; documented idempotency-key uniqueness per (stream, key).
4. **Receipt observability.** Added `failure_reason` + `duplicate_of`.
5. **Task safety.** Added `schema_version`; documented DRAFT-at-creation rule + "omitted writable_scope ≠ all-writable".
6. **Identity scoped, not built.** v0.1 actor identity = OS principal (Linux user + Tailscale); crypto-key identity (keys/rotation/revocation) → NOT_IN_V0_1.

## Accepted but DEFERRED (kernel-impl or later phase, on purpose)
- Cross-object invariants that JSON Schema can't express across documents (task.protected ↔ approval presence; evidence_refs bound onto transitions) → enforced by the **kernel runtime** + neuro-symbolic guards, not the schema. Tracked for Phase 5 wiring.
- Deep sub-typing of `inputs/constraints/acceptance` → kept as string arrays for v0.1 simplicity (NOT_IN_V0_1 ethos: least complexity). `acceptance[]` items SHOULD be testable assertions (documented).
- Full cryptographic actor identity + PQC signatures → NOT_IN_V0_1.

## Note
Single-auditor verdict treated conservatively: every Codex finding that was cheap + correct was applied, not argued down. When Gemini quota returns, re-run the same prompt for the independent second lens.
