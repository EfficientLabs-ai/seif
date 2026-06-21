# Research → Implementation Matrix (SEIF v0.2 Evidence Engine)

Date: 2026-06-22 · Authority: founder v0.2 directive. Status vocabulary is binding; **never upgrade a
status by linguistic confidence** — only by code + selftest (BUILT), live runtime (WIRED), or scored
result (MEASURED).

MEASURED · BUILT · WIRED · EXPERIMENTAL · TARGET · REJECTED(for v0.2)

## Measured truth (the only causal/empirical claims we may make)
| Claim | Status | Evidence |
|---|---|---|
| Naive self-check ≤ blind; independent gate > naive (+10.8pp, strict superset) | **MEASURED** | FINDINGS 001-003, n=20/37 |
| It's the gate, not the turns (v2 81.1 vs v3-nogate 73.0, +8.1pp; v3≈blind) | **MEASURED (direction)** | FINDINGS 004, n=37/1-seed, p≥0.13 — NOT significant |
| 3-seed significance | **EXPERIMENTAL (running)** | `run_seeds.py`, seeds 2-3 in flight |

## Already built (Phase 0 / Wave 1)
| Capability | Status | Where |
|---|---|---|
| Hardened disposable sandbox (no host footprint) | **BUILT** | `logos/sandbox.py`, `logos/arm_b_testbed.py` |
| Typed kernel: envelope · FSM · deny-by-default · hash-chain ledger · receipts | **BUILT** | `kernel/seif_kernel.py` |
| Eval-mode harness w/ oracle-leak guard (regression disjoint from graded) | **BUILT** | `logos/harness.py` |
| `/seif` project-mode loop (clean-room → verify on real tests → branch/PR → receipt → rollback) | **BUILT, proven e2e** | `logos/project_harness.py`, `logos/seif_run.py` |
| SEIF action-ledger (records every tool call, hash-chained, redacted) | **WIRED** | `~/.claude/hooks/seif-ledger.py` |
| ECP continuity (state survives compaction) | **WIRED** | session hooks |

## v0.2 build (this directive) — binding order
| WP | Mechanism | Status → target | Notes |
|---|---|---|---|
| A | **Evidence Contract** (frozen, hashed proof obligations before candidate) | TARGET → **BUILDING** | the new stopping rule; root dependency |
| B | **Candidate-blind Test Architect** (independent test author; never sees candidate/gold/hidden) | TARGET | breaks the confirmation-bias loop |
| C | **Mutation adequacy gate** (do tests reject plausible-wrong impls?) | TARGET | thresholds EXPERIMENTAL until baselined |
| D | **Multi-channel Evidence Oracle** (L0–L10, tri-state ACCEPT/REJECT/INSUFFICIENT) | partial → expand | L0-L2 exist in `harness.py`; L3-L10 TARGET; LLM never overrides a hard gate |
| E | **Reward-hacking / integrity guard** | TARGET | detect test/harness/scorer tamper, gold/hidden access |
| F | **Structured trajectory summaries** (not raw transcripts) | TARGET | context + DOP candidate unit |
| G | **Assumption graph skeleton** (logical invalidation; NOT git reset of main) | TARGET (minimal) | full ATMS only if measured need |
| H | **MCP telemetry profile** (typed resources; SEIF, not MCP, authorizes) | TARGET | |

## Experimental (guide only — never determine correctness/promotion)
| Mechanism | Status | Guard |
|---|---|---|
| Process Reward Models | **EXPERIMENTAL** | advisory only; stored separate from executable evidence; do NOT train this wave |
| Trace distillation → skills | **TARGET** | DOP shadow → held-out → human approval; "evidence-gated skill candidate generation", not perpetual self-improvement |
| Evidence-ranked Best-of-N | **TARGET (after D)** | only after the oracle can rank; diversity-enforced |
| Context Compiler 2.0 (graph/trace/policy-aware) | **TARGET** | selection quality > volume |

## REJECTED for v0.2 (do not build now)
MCTS / LATS / I-MCTS / AdverMCTS (best-of-N first; define state/action/reward + prove benefit first) ·
automatic prompt evolution · federated/auto training · automatic skill promotion · Neo4j/RedisGraph
(SQLite + AST index first) · Firecracker (Docker not yet the measured bottleneck) · new foundation model ·
public OpenLogos cloud · autonomous production merges.

## Claim guardrails (binding, from the directive)
Deterministic **boundaries around probabilistic generation** (never "100% determinism/security/accuracy").
Best-of-N ≠ MCTS. ATMS invalidates beliefs; the worktree manager destroys candidate workspaces; **main is
never auto-reset**. Exit-0 ≠ correct → multi-channel evidence. ML-KEM = key encapsulation; ML-DSA =
signatures. No provider-infra performance claims without traceroute/contract evidence. Training data:
local-first, opt-in, rights-cleared. Explicit **INSUFFICIENT_EVIDENCE** state — never fold unknown into success.
