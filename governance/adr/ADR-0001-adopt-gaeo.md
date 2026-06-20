# ADR-0001 — Adopt GAEO as SEIF's GitHub projection

- **Status:** Proposed (founder gate pending) · **reality_state:** STANDALONE · **truth_class:** ARCHITECTURE
- **Date:** 2026-06-20 · **Deciders:** neo (sovereign) · proposed by Claude

## Context
The triad (Claude/Codex/Gemini) should operate as an auditable engineering organization with GitHub as source of truth. SEIF already defines the control plane (task/event/artifact/claim/approval/receipt + FSM + protected actions). GAEO is the proposal to render that plane in GitHub's native primitives so all planning, verification, and history are observable and enforced.

## Decision
Adopt GAEO (`governance/GAEO.md`) as the GitHub projection of SEIF — **scoped to the v0.1 first slice**: a single enforceable loop (Issue → branch → PR → recorded Codex+Gemini reviews → required checks → neo merge), with ARB/CAB/ICS/EIU/RMS and enterprise functions adopted **semantically** (labels/templates/conventions), promoted to standing processes only on proven volume.

## Consequences
- (+) Three-mind consensus + sovereignty become mechanically enforced (branch protection, CODEOWNERS, required checks).
- (+) Every decision/tradeoff/rollback becomes searchable institutional memory.
- (−) Real token/time cost if the maximalist 50-person org is run continuously → bounded by the v0.1 slice + NOT_IN_V0_1.
- Honest limit: separate-identity model autonomy is NOT yet live (Claude is sole executor; Codex read-only/broken sandbox; Gemini advisory). Recorded as ARCHITECTURE, not CLAIM.

## Alternatives considered
1. **Free-form agent group chat** — rejected: not auditable, no enforcement (violates evidence-first).
2. **Full GAEO maximalism on day one** (ARB/CAB/ICS/EIU/RMS as services + weekly multi-model reports) — rejected for v0.1: sprawl, uninspectable TCB, against active commercialization focus.
3. **Keep triad as ad-hoc reviewers only** — rejected: loses traceability and the institutional-memory flywheel.
