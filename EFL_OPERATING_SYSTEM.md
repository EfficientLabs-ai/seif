# Efficient Labs Operating System — Master Architecture & Path to Launch

> The single canonical map of the full stack and the sequence to "launch-ready." Consolidates
> `SEIF_LOGOS_PRD.md` (vision + reconciliation), `eval/LOGOS_ROADMAP.md` (adversarial roadmap),
> `logos/FINDINGS_001.md` (measured proof). Claim discipline binding: tags are **MEASURED** (proven
> on disk), **BUILT** (code exists + selftested), **WIRED** (operating in the live runtime now),
> **TARGET** (designed, not built). Nothing is "done" until it's WIRED or MEASURED.

## Thesis
A single LLM cannot ship production software alone — it lacks operational discipline, not intelligence.
The fix is architectural: decouple probabilistic **generation (LOGOS)** from deterministic,
evidence-based **verification (SEIF)**, run it on durable **continuity + memory**, and make every step
**provable**. StratosAgent is the runtime that composes the whole stack so you plug in any LLM and
execute. Efficient Labs' moat is not a smarter model — it's **verifiable, non-degrading engineering with
a receipt**.

## The measured proof (why this is real, not a deck)
SWE-bench-Verified, official scorer, n=20→37, 1 seed (`logos/FINDINGS_001.md`):
- Blind one-shot **70%** → naive self-check **55%** → independent-verification **75%**. **[MEASURED]**
- v1<blind proves self-verification *degrades* performance; v2⊃v1 (+20pp) proves *independent*
  verification fixes it. v2-vs-blind is a tie at n=20 (not yet a beat). 37-instance + seeds in progress.

## The stack (layers, bottom → top) with honest status
| Layer | Role | Status | Where |
|---|---|---|---|
| **Continuity / ECP** | state survives compaction; sessions resume from the ledger | **WIRED** | SessionStart/PreCompact hooks; `command-center` ledger; memory files |
| **Tripartite Memory** | L1 Redis cache · L2 Postgres episodic+counterfactual · L3 AST/graph deterministic retrieval | **TARGET** (substrate partial) | PRD Pillar 4 |
| **SEIF kernel** | typed task envelope · FSM legality · deny-by-default policy gate · hash-chained ledger · receipts · evidence-gated accept | **BUILT** (runtime-wiring gated) | `kernel/seif_kernel.py` |
| **Agent Harness** | EVIDENCE verification — exit-code adjudication, regression set provably disjoint from graded, signed receipt | **BUILT (core)** | `logos/harness.py`, `logos/sandbox.py`, `logos/arm_b_testbed.py` |
| **LOGOS engine** | HTN decomposition · best-of-N search · execution-feedback · ATMS rollback | **BUILT (eval)**, runtime **TARGET** | `logos/swe_arm_b_v2.py` (gate), eval arms |
| **Orchestration** | parallel agents, workflows, background batches, multi-model team (Claude builds → Codex verifies → Gemini tie-breaks) | **WIRED** | Workflow tool, subagents, this session |
| **Integrations** | self-hosted Composio (tools/actions) + Nango (auth) so any LLM gets real-world reach | **TARGET** | PRD §integrations |
| **StratosAgent (runtime)** | composes ALL layers into one plug-in-any-LLM super-agent | **TARGET (assembly)** | `~/StratosAgent` |

## Honesty guardrails (the brand is "you can prove it")
1. "100%" (provability/determinism/accuracy) = TARGET language. We do **deterministic verification of
   probabilistic generation** — the *check* is deterministic, the *generation* is not.
2. No capability claim beyond the measured number + CI; pass@1 only (pass@N labeled oracle upper bound).
3. **Oracle-leak is fatal** — any feedback signal must be provably disjoint from graded truth (built into `harness.py`).
4. Self-modification of the runtime (hooks, policy, secrets) is **founder-gated** — the AI never rewires
   itself silently. (Demonstrated 2026-06-21: the deny-gate blocked an unauthorized PostToolUse install.)

## Path to launch-ready (phased — incremental, each piece verified before the next)
- **P0 — Close the proof (now):** finish 37-instance × 3-arm scoring + the no-gate ablation + seeds →
  defensible A/v1/v2 numbers. *(in flight)*
- **P1 — The Cage in YOUR loop:** project-mode harness (any repo + its own tests) · ATMS git-worktree
  rollback · `/seif` driver (generate → harness-verify on your tests → accept/rollback → receipt →
  branch/PR, never main) · **founder-approved** SEIF action-ledger hook (SEIF records my work by
  default). Dogfood on **StratosAgent's** real test suites.
- **P2 — The Brain:** diverse best-of-N + execution-grounded ranker; heavier-repo eval → degradation
  **slope**; gate calibration (measured FP/FN).
- **P3 — StratosAgent as runtime:** assemble ECP+SEIF+LOGOS+Harness+Memory behind one interface;
  self-hosted Composio + Nango for real-world tool/auth reach; "plug in any LLM, execute."
- **P4 — Memory flywheel:** Tripartite Memory captures verified trajectories (proprietary dataset).

## Definition of "launch-ready" (the bar we're driving to)
1. `/seif` runs end-to-end on a real EFL repo: change → evidence-verified → receipted → PR, with you at the merge gate. **[→ WIRED]**
2. SEIF records every agent action by default (founder-approved hook). **[→ WIRED]**
3. The eval shows a defensible result (v2 strictly fixes v1; v2≥blind with CIs at scale). **[→ MEASURED]**
4. StratosAgent boots the stack and executes a real multi-step task with a flat-enough degradation curve to demo. **[→ MEASURED]**
5. One signed receipt you can hand a skeptic: "don't trust me — verify it." **[→ the moat]**

## The pivot (what this unlocks)
When launch-ready, energy moves off building/testing → **personal brand + EFL brand + organic social +
first revenue**, with the system *itself* as the proof and the story: ending **data sharecropping**, and
re-teaching the true history/principles/frameworks of AI. The content engine (PR #1 merged, gate PR #2)
is already staged to carry that arc — fed by the receipts this OS produces.
