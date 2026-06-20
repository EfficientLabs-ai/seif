# ADR-0002 — Adopt the LOGOS execution engine on SEIF

- **Status:** ACCEPTED (founder-approved 2026-06-20)
- **reality_state:** STANDALONE (building) · **truth_class:** ARCHITECTURE
- **Context:** `eval/LOGOS_EXECUTION_PLAN.md`, `eval/EVALUATION.md`, and the `logos-research` workflow synthesis (6 agents, high-confidence).

## Context
SEIF's kernel/FSM/ledger are the trusted base + truth-maintenance substrate. The missing layer is a deterministic **execution engine** (between AUTHORIZED and ACCEPTED) that wraps probabilistic models in decomposition + search + verification + rollback to solve long-horizon SWE without context collapse.

## Decision
Adopt **LOGOS** as that execution plane, built OUTSIDE the kernel TCB, calling it as a library. Research-locked component choices:
- **HTN** = thin methods table (not formal HTN); the existing FSM is the task-decomposition backbone.
- **Search** = best-of-3 PARALLEL + deterministic rerank (`grading-pass > PASS_TO_PASS > diff-size > confidence-last`); greedy+execution-feedback default. **MCTS deferred.**
- **Verify** (load-bearing) = execution-feedback every step + hallucinated-dependency check + independent verifier (Codex) on accept + Gemini tie-break.
- **Reward-hacking defense** = three-tier test split (visible / hidden-grading / OOD); acceptance scored by the harness on HIDDEN tests, never self-reported.
- **ATMS** = event ledger + thin assumption ledger (no label-propagation; deferred).
- **Sandbox** = Docker, warm-cached, locked isolation (`logos/sandbox.py`). bubblewrap rejected (broken on this kernel).
- **Concurrency** = single-writer; parallelism only at the best-of-3 candidate level.

## Honest target (claim discipline)
NOT 100%. Self-hosted absolute ceiling ~42–50%. The v0.1 target is a **reproducible ≥4–6pp delta vs a matched baseline at p<0.05**, and the **degradation curve** (SEIF's success-vs-task-length slope staying flatter than baseline) — that gap is the publishable, defensible claim. Numbers are claimed only when measured on held-out grading tests.

## Consequences
- Build sequence Ph0(done)→Ph1(one task end-to-end)→Ph2(baseline arm)→Ph3(SEIF arm, gated ≥4–6pp p<0.05)→Ph4(best-of-3)→Ph5(ablation + degradation-curve writeup).
- Deferred (measurement-gated, `NOT_IN_V0_1.md`): formal HTN, label-propagation ATMS, CSP/SMT, multi-agent 2PC, MCTS, Firecracker, PQC signing.

## Alternatives considered
- Naked frontier model (the rat race) — rejected: hits the same ceiling, no sovereignty, no proof.
- Full formal HTN/ATMS now — rejected: no production precedent, ~20% cost for ~70% benefit via the FSM+ledger substrate; don't formalize what we can't measure.
