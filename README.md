# SEIF — Sovereign Engineering Intelligence Fabric (v0.1)

> **No model owns continuity. SEIF owns continuity.** Neural models propose · symbolic policy determines admissibility · isolated runtimes execute · tests/evidence verify · Neo authorizes protected actions · the event ledger preserves continuity.

SEIF v0.1 is a **small trusted microkernel** — NOT a 12-service "fabric". It does exactly seven things; everything else is replaceable and lives outside the trusted base.

## The 7 kernel functions
1. Authenticate actor identity (Linux users + Tailscale).
2. Validate typed task envelopes (`schemas/task.schema.json`).
3. Authorize proposed actions (policy + `governance/protected_actions.yaml`).
4. Validate legal state transitions (`governance/workflow_transitions.yaml`; backed by `command-center/04_skills/neuro-symbolic/fsm.mjs`).
5. Append immutable events + receipts (`schemas/event.schema.json`, `schemas/receipt.schema.json`).
6. Gate protected actions for Neo (`schemas/approval.schema.json`).
7. Accept/reject artifacts by evidence (`schemas/artifact.schema.json` + `evaluation-pass` skill).

## Canonical order of truth (evidence-first)
Original evidence → signed append-only events → validated current-state records (`claims`) → graph / memory / context / dashboards. **Derived projections may never rewrite original evidence.**

## Layout
- `phase0/` — read-only reality inventory (CLAIM-grade), dual-audited. **Read this first.**
- `schemas/` — JSON Schema contracts (task, event, artifact, claim, decision, approval, receipt).
- `governance/` — workflow transition table + protected-action matrix.
- `NOT_IN_V0_1.md` — the scope guard. If it's in there, it is NOT built in v0.1.

## Build on what exists (Phase 0 finding)
~70% of the kernel substrate already lives in `command-center/04_skills/neuro-symbolic/` (fsm, graph-query, runtime, state-projector, workflow-schema) + context-compiler + evaluation/evolution/harness skills + JSONL event ledgers. v0.1 = **formalize + connect + correct drift**, not greenfield.

Status: VISION (this scaffold). No component is CLAIM until tested + reviewed + (if protected) owner-approved.
