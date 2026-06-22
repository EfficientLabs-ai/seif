# EFL Architecture & Strategy Addendum (reconciled 2026-06-22)

This addendum folds a founder strategy session into the EFL canon **reconciled against the actual codebase**
(read-only 3-repo audit with file evidence). It exists to keep the build coherent with the vision while
holding claim discipline: every concept is labeled **BUILT / PARTIAL / TARGET**, never aspiration-as-fact.

Companion canon: `EFL_OPERATING_SYSTEM.md`, `SEIF_LOGOS_PRD.md`, `CLAIMS_AND_EVIDENCE_LEDGER.md`,
`RESEARCH_TO_IMPLEMENTATION_MATRIX.md`, `GOVERNED_INTEGRATION_FABRIC.md`.

## 1. The framing (vocabulary we adopt)
**Tripartite Memory is a cognitive state stack, not a database system:**

| Layer | Role | "Thinking…" |
|---|---|---|
| L1 Redis / file | working set, attention | **NOW** |
| L2 Graph | deterministic structure/relationships (replaces fuzzy vector similarity) | **STRUCTURE** |
| L3 DB / ledger | immutable truth (receipts, outcomes) | **HISTORY** |
| **L4 Checkpoints** *(proposed)* | verified, replayable system snapshots (state+proof+context signature) | **STATE** |

Pitch: a **Versioned Intelligence System** — intelligence evolves like git commits / docker images, not
chat history + embeddings. The differentiator we can defend *today* is narrower and real: **executable
evidence + signed receipts + an independent gate** (MEASURED: 81% gated vs 70% blind, `logos/FINDINGS_001.md`).

## 2. Reconciliation — concept × build-state (file-grounded)

| # | Concept | seif | StratosAgent | Atmosphere |
|---|---|---|---|---|
| 1 | Verified-state rollback / ATMS | PARTIAL¹ | ABSENT | ABSENT |
| 2 | Hash-chained receipts / truth ledger | **BUILT** | **BUILT** (PQC-signed) | **BUILT** (PQC-signed) |
| 3 | Evidence Contract / freeze-before-change | **BUILT**² | PARTIAL (write-ahead intent) | ABSENT (post-hoc bind) |
| 4 | Tripartite Memory (L1/L2/L3) | PARTIAL³ | PARTIAL³ | PARTIAL³ |
| 5 | **L4 Checkpoint Engine** | **BUILT**⁷ | ABSENT | ABSENT |
| 6 | **ASRS self-healing feed-forward** | PARTIAL⁴ | PARTIAL⁴ | PARTIAL⁴ |
| 7 | **Checkpoint-aware delta planning** | ABSENT | ABSENT | ABSENT |
| 8 | Integrity / reward-hacking gate | **BUILT** | PARTIAL (trace-integrity) | PARTIAL |
| 9 | Model routing / **NVIDIA NIM** | ABSENT⁵ | PARTIAL⁵ | PARTIAL⁵ |
| 10 | Mesh / proof-of-compute | ABSENT (non-goal) | PARTIAL (signal) | **BUILT**⁶ |
| 11 | DOP / ARI | ABSENT | ABSENT | ABSENT (settlement MOCK) |

¹ "rollback" = discard the ephemeral worktree back to base HEAD, not restore a stored *healthy snapshot*.
² freezes the proof *obligations* + ledger anchor, not a runnable system snapshot.
³ exists **three divergent ways** and is **not unified**: seif (L1 **Redis live** via the dedicated
  `seif-redis` container — localhost-only, auto-detected via `~/.config/seif/redis.url`, file fallback when
  absent — + JSONL-episodic-L2 + graphify-L3), StratosAgent (in-memory graph-query; "L1/L2/L3" are
  doc-context folders), Atmosphere (LanceDB vector + FTS5). The unification contract (this PR) is the shared target.
⁴ ingredients exist (auto-rollback, per-failure lessons, trajectory summaries) but **nothing consumes them at
  runtime to avoid a failure CLASS** — e.g. `logos/seif_loop.py` fetches prior attempts and only *counts* them;
  the real failure-class fixes to date were human code changes, not feed-forward.
⁵ routing **decision** layer is real + tested (`StratosAgent/src/routing/model-router.js`: privacy>capability>
  cost>fallback) but **no model is actually called**, and **no NIM/Nemotron/Qwen/DeepSeek adapter exists**.
⁶ `atmosphere-core/.../mesh-node.mjs`: DHT, proof-of-capacity hash-chain, leader-election. Settlement is MOCK
  (PaymentEngine mock; Solana never broadcast).
⁷ `logos/checkpoint.py` (built): proof-gated create (refuses unverified states), hash-chained lineage,
  `last_healthy`, `restore` (materialize a verified commit into a worktree), ASRS `record_failure` forensics.
  **Wired into the gate** — every VERIFIED `seif_run` registers a healthy checkpoint; every rejection records
  forensics. NOTE: **checkpoint-aware delta planning (row 7) is still ABSENT**, and the live loop records
  forensics + rolls back to BASE (auto-restore-to-last-healthy is the next increment), so the full
  "self-healing versioned intelligence" is PARTIAL — the engine + creation-on-success + the rollback
  primitives are real; LOGOS planning against checkpoints is not yet.

## 3. Net-new build priorities (what the vision actually adds, cheapest-first)
1. **Close the ASRS feed-forward loop** *(cheapest, highest leverage)* — recorded forensics → fed into the
   next plan/prompt so a failure *class* isn't repeated. Concrete first step: in `logos/seif_loop.py`, feed
   the prior reusable lessons / prohibited-reuse for a `task_id` into the runner prompt (today they're fetched
   and discarded). Make it MEASURED (does it cut repeat failures?).
2. **Unify Tripartite Memory** — one contract the three repos share, instead of three divergent partials.
3. ~~**L4 Checkpoint Engine**~~ — **DONE** (`logos/checkpoint.py`, wired into `seif_run`). NEXT here:
   **checkpoint-aware delta planning** (LOGOS emits deltas vs the last checkpoint, not full rewrites) +
   **auto-restore-to-last-healthy** in the live loop (today: forensics recorded + rollback to base).
4. **NIM provider adapters** into the existing router seam — model diversity without becoming a model company.

LOGOS=checkpoint-aware planner · SEIF=checkpoint validator (legal transitions, rollback on violation) ·
Harness=checkpoint creator (exec→tests→freeze on success). This is "Git + Docker + CI/CD + AI reasoning +
self-healing rollback, unified." **TARGET, not built** — sequence behind real users.

## 4. Business model (positioning)
**EFL = the OWNERSHIP LAYER, not the model layer.** Don't be a wrapper/chatbot/marketplace. Users choose
**outcomes, not models.** Layered stack: Frontier models (external) → **StratosAgent** (routing+governance)
→ **Atmosphere** (sovereign infra) → **SEIF/LOGOS/DOP/ARI/receipts** (governance) → **Efficient Labs** (parent).

**NVIDIA NIM** = ship model diversity *without* a model company: default stack = NIM open models
(Nemotron/Qwen/Llama/DeepSeek, free, sovereign), premium = Claude/GPT/Gemini. The router *decision* layer
already exists — this is wiring adapters into a seam, not a net build.

**Product packaging (the real gap):** Consumer → install StratosAgent (free, OSS) · Developer → EXOS
(*TARGET*) · Founder → run business / govern AI / ARI · Enterprise → governed autonomous infra. Everything
else stays underneath.

## 5. The honest bottleneck
Per the session's own best insight (and `project_valuation_gap`): **the bottleneck is packaging /
distribution / trust / leverage — not tech.** Investors care about demand/adoption/retention. Next valuation
jump = **first 5 → 50 → 500 users**, not new primitives. The launch test: land on efficientlabs.ai →
understand in <30s → install StratosAgent in <3min → value in <10min. Solve that and the rest compounds.
GTM resources (accelerators, credits, reference systems) tracked in memory `reference_efl_gtm_resources`.
