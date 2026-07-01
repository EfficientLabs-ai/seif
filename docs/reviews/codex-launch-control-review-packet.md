# Codex launch-control review packet

Status: draft

## Review scope

- SEIF reconciliation artifacts.
- ECP lockfile/audit branch.
- Node runtime standardization branches.
- Sovereign state plane ADRs and schema.
- Stratos Shield threat model.
- Codex-SEIF-ECP bridge design.
- ContinuityMemory contract.

## Confirmed safe behaviors so far

- No vault files, `.env` files, private keys, tokens, or production credentials were read.
- SEIF untracked files were archived before cleanup.
- Governance files preserved from the archive match `origin/main` byte-for-byte.
- Tests were run after reconciliation and runtime changes.

## Required independent review checks

- Ensure no secret-like paths are tracked.
- Ensure schema does not imply storing plaintext secrets.
- Ensure bridge design denies gitignored/vault/env paths by default.
- Ensure Node runtime narrowing does not break intended public distribution.
- Ensure Postgres backup runbook includes restore proof before live billing.

## Merge recommendation

Do not merge automatically. Neo review required for ADR authority, database topology, Stripe activation timing, and GitHub protection enforcement.
