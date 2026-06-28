# Launch-control status matrix

Updated: 2026-06-28

| Area | Status | Evidence | Remaining risk |
|---|---|---|---|
| SEIF reconciliation | Green | `main` equals `origin/main` at `0a0c002`; safety branch and archive created | Need PR/report review for audit trail |
| SEIF tests | Green | 379 unit tests pass; kernel selftest pass; tripartite selftest pass | ResourceWarning cleanup is non-blocking |
| ECP lockfile/audit | In progress | Branch `codex/ecp-lockfile-audit`; npm ci/test/bench/audit pass | Needs review/commit/push |
| Node runtime | In progress | PM2 all Node 22.22.3; atmosphere-core and StratosAgent branches patched/tested | TheAtmosphere/node-runner dirty repo not patched yet |
| Codex bridge | Design ready | `docs/bridge/codex-seif-ecp-bridge.md` | Needs dry-run implementation and red-team tests |
| Memory contract | Design ready | `docs/memory/continuity-memory-contract.md`; `memory/continuity_contract.py` | JS adapters not implemented |
| GitHub governance | Partially green | CODEOWNERS, PR template, issue templates, PR discipline workflow on SEIF main | Branch protection must be enforced in GitHub UI/API |
| Observability/backups | Draft | runbooks added | Need off-host backup target and restore drill |
| Stripe/Postgres | Design ready | ADR, schema, webhook contract, state machine | No production deploy; no live Stripe mode |
| Stratos Shield | Threat model ready | threat model doc added | Needs implementation and scanner tests |
