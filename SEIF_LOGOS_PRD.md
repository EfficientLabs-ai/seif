# SEIF + LOGOS — Architecture PRD & Canonical Vision

> **STATUS BANNER (claim discipline binding):** This is the **north-star vision**. Every capability
> claim here is **TARGET** unless the *Reality Reconciliation* table below marks it MEASURED. The
> founder's source thesis is preserved verbatim in §"Vision (founder canon)". The reconciliation +
> the honesty guardrails are the engineering team's binding annotations — they override any
> superlative in the vision text when we communicate externally.

## The thesis in one paragraph
A single LLM cannot build production software on its own — not because it lacks intelligence, but
because it lacks **operational discipline**: left to verify its own work it converges prematurely
(writes a weak test, passes a half-fix, ships broken code). The fix is architectural: **decouple the
probabilistic Generator (LOGOS) from a deterministic, evidence-based Verifier (SEIF)**, and make
every step **provable**. The product is not just the code — it's the *receipt* proving how it was
built and that it didn't break anything.

## Reality Reconciliation (MEASURED vs TARGET, 2026-06-21)
| Pillar / claim | Status | Evidence / note |
|---|---|---|
| Single-LLM self-verification degrades performance | **MEASURED (direction)** | A blind 70% · v1 naive-self-check **55%** · v2 indep-gate **75%**, n=20/1-seed. v1<A is the proof; not yet significant. `logos/FINDINGS_001.md` |
| Independent verification fixes the regression | **MEASURED (strong pattern)** | v2 ⊃ v1, +20pp, strict superset, p=0.125 |
| Independent verification beats blind | **TARGET** | +5pp = tie at n=20 (p=1.0). Needs scale-up. |
| Locked execution sandbox (no host footprint) | **MEASURED / BUILT** | `logos/sandbox.py`, `logos/arm_b_testbed.py` (net=none, caps dropped, ephemeral) |
| SEIF kernel: typed envelope · FSM legality · deny-by-default gate · hash-chained ledger · receipts · evidence-gated accept | **BUILT** | `kernel/seif_kernel.py` (adversarially hardened) |
| Agent Harness = EVIDENCE oracle (exit-code adjudication, regression suite **disjoint from graded**, signed receipt) | **BUILT (core)** | `logos/harness.py` — disjoint guard Codex-reviewed; the regression suite is PROVABLY disjoint from FAIL_TO_PASS∪PASS_TO_PASS (file-excluded **and** `--deselect`ed) |
| Best-of-N / MCTS over candidates | **TARGET** | Phase 2 |
| HTN decomposition (fresh context per subgoal) → flat degradation curve | **TARGET (unmeasured)** | the actual goal; needs a benchmark long enough to *induce* collapse |
| ATMS rollback (git-worktree checkpoints) | **TARGET** | Phase 1/3; kernel FSM has the state machine |
| Tripartite Memory (Redis L1 / Postgres L2 / AST-graph L3) | **TARGET** | partial substrate exists in command-center |
| Provability moat (signed, replayable receipts) | **BUILT (core), TARGET (full)** | ledger + receipts exist; "100% cryptographic provability" is the target, not a current claim |

## Honesty guardrails (the brand is "you can prove it" — these are non-negotiable)
1. **"100%"** (provability, determinism, retrieval accuracy) is **TARGET language only**. What is
   deterministic is the **verification** (OS exit codes), not the **generation** (probabilistic).
   Say: *"deterministic verification of probabilistic generation."*
2. **No "75% beats 70%"** until the scale-up clears significance. Current honest claim: *"independent
   verification strictly fixes the self-check regression (+20pp over naive); vs blind it's a tie at n=20."*
3. **Oracle-leak is fatal.** Any regression/feedback signal MUST be provably disjoint from the graded
   set (`harness.assert_disjoint` + `--deselect`), asserted in code, logged to the ledger. A leak
   voids every number — including past ones.
4. **The degradation curve only counts** if the benchmark is long enough to induce collapse. A flat
   curve on a too-short benchmark is a *finding* ("SWE-bench is too short to test this"), not a win.
5. Report **pass@1** as the only capability claim; **pass@N** is always labeled an oracle upper bound.

## Build sequence (merged: founder PRD phasing × adversarial roadmap)
- **Phase 0 — believe the result** (running now): scale to 37 light instances + 3 seeds + the
  **no-gate ablation** (the moat-decider: is the win the *gate* or just *more turns?*). No new claim.
- **Phase 1 — The Cage / evidence verifier** (next, highest lever): the **Agent Harness** (`harness.py`)
  becomes the verifier — single LLM generates patch + its own differential test; the harness runs it +
  the **disjoint** regression set in the sandbox; **exit code decides**, not an LLM; signed receipt.
  This is the *single-LLM-architecture* proof: the win must come from the harness, provable with ONE
  model — that's what makes it an adoptable standard, not "we threw more models at it."
- **Phase 2 — The Brain**: diverse best-of-N (real model/prompt diversity, not temperature samples),
  execution-grounded ranker (LLM verdict = tie-breaker only); rebuild the eval on heavier repos to
  get a real degradation **slope**; calibrate the gate (measured FP/FN).
- **Phase 3 — Long-horizon machinery** (gated on a measurable slope): HTN fresh-context subgoals on
  the SEIF ledger; ATMS rollback (git-worktree checkpoints). Only default these once the slope chart
  shows a crossover where they win.
- **Phase 4 — The Flywheel**: Tripartite Memory captures verified trajectories (the proprietary
  dataset); optional OpenLogos SDK.

## The defensible artifact at every stage
*"Our scaffold, this exact subset, this scorer, this seed-count, this CI, this $/solve — and a signed
receipt for every step."* Never a leaderboard rank. That receipt is the moat.

---

## Vision (founder canon)

> The following is the founder's source articulation, preserved as the north star. Read it through the
> guardrails above — superlatives here are TARGETs.

### The Single-LLM Fallacy
Treating LLMs as sovereign, self-verifying systems is the industry's core architectural flaw. An
autoregressive model that generates a fix naturally generates a biased, superficial test to validate
it — it passes a half-fix and halts, shipping broken code. A single LLM loop cannot build
production-grade software: the intelligence is there, the operational discipline is absent.

### LOGOS (Generator) ⟂ SEIF (Verifier)
Physically decouple generation from verification. **LOGOS** does the cognitive lifting: HTN
decomposition, best-of-N candidate generation, state-space search. **SEIF** is the tamper-proof
boundary enforcing separation of powers: independent (non-author) verification, and — crucially —
**executable evidence** over opinion. The compiler, not the LLM, has the final say.

### Beating the degradation curve
HTN feeds the model isolated, atomic sub-goals in fresh, clean contexts so it is never exposed to the
whole problem; per-step context becomes O(1) in task length instead of O(length). ATMS intercepts a
failed verification and hard-rolls-back to the last verified state, pruning the hallucination tree
instead of letting the model loop on its own mistakes.

### The Agent Harness (execution gateway) — 5-step protocol
1. **State isolation** — checkout the last verified commit into an ephemeral git worktree.
2. **Patch & test injection** — apply the candidate + the AI's own tests + the repo's regression set
   *(SEIF caveat: the regression set must be provably disjoint from any graded tests — see guardrail 3)*.
3. **Deterministic execution** — run in the locked sandbox with hard timeout + resource caps.
4. **Adjudication** — read the raw OS exit code (0 = verified by evidence; >0 = broken). No LLM
   interpretation.
5. **Receipt** — sign an immutable JSON receipt (task, prompt hash, patch hash, test stdout,
   harness signature) into the ledger.

### The moat: provability over promises
Reject the race for "100% on synthetic benchmarks" as a marketing metric. The moat is **provability**:
an immutable, replayable ledger of every state transition, tool call, test execution, and verification
vote. Enterprises don't need a smarter LLM; they need a system that *proves* the LLM cannot break their
company. SEIF provides that proof.

### Four pillars (target architecture)
- **LOGOS** — HTN planner + MCTS/best-of-N generation across models.
- **SEIF** — policy-as-code (L0 human sovereignty), ATMS state/rollback.
- **Agent Harness** — isolation → injection → deterministic execution → exit-code adjudication → receipts.
- **Tripartite Memory** — Redis working cache (L1), Postgres episodic ledger incl. counterfactuals (L2),
  AST/Neo4j semantic graph for deterministic context retrieval (L3).

### Success metrics
- **Primary:** flatter degradation curve (resolve rate vs task length — flat from step 1 to step 50).
- **Secondary:** zero-regression rate (harness-enforced).
- **Moat:** the cryptographically signed SEIF receipt.
