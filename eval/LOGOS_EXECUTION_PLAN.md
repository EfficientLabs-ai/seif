# LOGOS Execution Plan (v0.1) — research-grounded

Source: `logos-research` workflow (6 agents, high-confidence). This operationalizes `EVALUATION.md` + the LOGOS research into a buildable, honestly-measurable sequence.

## 0. The honest target (read this first)
The evidence is clear, so I won't let us claim what we can't prove:
- **Self-hosted absolute ceiling** for a Claude/Codex-class agent: ~**42–46%** on SWE-bench-Verified (agentic loop + execution feedback); ~**46–50%** adding FSM + ensemble verify; **~48–50% is the task-ambiguity ceiling even for frontier reasoning models**, with sharp diminishing returns past ~5× token budget.
- **So the v0.1 target is a DELTA, not 100%, not an absolute headline:** a reproducible **≥4–6pp** improvement of SEIF (Arm B) over a matched baseline (Arm A) at **p<0.05** with non-overlapping 95% CIs.
- **The novel, defensible claim = the DEGRADATION CURVE:** SEIF's success-vs-task-length slope staying measurably **flatter** than baseline as tasks get longer. *That gap is the "own + prove your work" moat* — more credible and more uniquely yours than any single %.
- **Ambition is not capped — it's instrumented.** If LOGOS genuinely beats the ceiling, the harness will *show* it, and then we claim exactly that number, measured. The instrument is what converts your thesis into a fact.

## 1. Architecture: reuse the TCB, add the execution plane
The kernel (`kernel/seif_kernel.py`, C0-hardened), the FSM (`governance/workflow_transitions.yaml`), and the hash-chained ledger **already are** the HTN backbone + truth-maintenance substrate. **Do not rebuild them.** LOGOS is the missing **execution plane between AUTHORIZED and ACCEPTED**, built *outside* the trusted base, calling the kernel as a library.

| LOGOS layer | Decision (research-locked) |
|---|---|
| **HTN** | Thin ~200-line **methods table** (data-driven codegen patterns + state predicates like file_exists), NOT formal HTN. FSM already does task decomposition; its FAILED→PROPOSED edge is the retry path. |
| **Search** | **best-of-3, PARALLEL**, deterministic rerank: `grading-test pass > PASS_TO_PASS > diff size > model-confidence (last)`. Default routine steps to **greedy + execution-feedback** (1.5–2× cost, +20–40%). **MCTS is OUT of v0.1.** |
| **Verify** (load-bearing) | execution-feedback every step (localize→bounded edit→test) + **independent verifier** (Codex checker) on the accept decision + Gemini tie-break on disagreement + **hallucinated-dependency check** (validate files/functions exist before tests). |
| **Reward-hacking defense** (non-negotiable) | **three-tier test split**: VISIBLE (agent iterates) / **GRADING-hidden** (harness scores acceptance, agent never sees) / secondary OOD. `tests_passed` = grading tests, computed by harness, **never self-reported**. |
| **ATMS** | existing event ledger + thin ~300-line **assumption ledger** (record choices; on contradiction, surface the violated assumption to the LLM). **No label-propagation ATMS** (v0.3+, measurement-gated). |
| **Sandbox** | **Docker, warm-cached.** `--memory=256m --cpus=1 --pids-limit=50 --cap-drop=ALL --read-only` (tmpfs /tmp) `--network=none --user`(non-root), external `timeout 5`, `--rm`. Exit-code demux (0=pass,1-2=fail,124=timeout,137=OOM). **Don't fix bubblewrap** (broken on this kernel). |
| **Concurrency** | single-writer v0.1; parallelism ONLY at the best-of-3 candidate level (isolated sandboxes → one winner recorded via one `append_event`). |

## 2. Build sequence
- **Phase 0 (DONE):** inventory + kernel + schemas + FSM + governance exist, C0-passed. *Only remaining blocker:* `neo` not in docker group (founder + one session restart).
- **Phase 1 — smallest credible slice:** ONE SWE-bench-Verified task, end-to-end, no search/ensemble. SWE-task→envelope adapter · Docker runner (exit demux + evidence) · single agentic loop (localize→edit→visible-tests→repeat, step budget + **rollback-on-repetition**) · score patch vs **hidden** grading tests via kernel gate. **Success = plumbing is real + replayable** (ledger + pinned Docker hash + git commit), NOT a resolve rate.
- **Phase 2 — baseline arm + 20-task harness:** curate 20 SWE-Verified tasks stratified 5 single-file / 5 multi-same / 5 multi-cross / 5 refactor. Lock visible/grading split. Run **Arm A (Claude alone)**, 3 seeds, identical seeds (never borrow a baseline from literature).
- **Phase 3 — SEIF_C0 arm (verify + exec-feedback, no search):** Arm B = loop + hallucinated-dep check + tightened localization + independent Codex verifier + FSM gating + ledger-externalized state. 3 seeds. **Promote only if B beats A ≥4pp at p<0.05** on the length-bucketed subset. Else report honestly + iterate.
- **Phase 4 — best-of-3 + assumption ledger (challenger C2):** parallel 3-candidate + deterministic rerank + assumption ledger. Must beat C0/C1 at p<0.05; **report token-cost delta** (+7% at 3× cost may not be worth it).
- **Phase 5 — ablation matrix + degradation-curve writeup:** 6 variants (full / −FSM / −ledger / −ECP / −verify / baseline), one knob at a time → the A-vs-B success-vs-length curve with 95% CIs, p-values, failure analysis, reproducible hashes. **This is the publishable artifact.**
- **Phase 6+ (DEFERRED, measurement-gated):** formal HTN, label-propagation ATMS, CSP/SMT, multi-agent 2PC, MCTS, Firecracker, PQC signing. Each needs a decision record proving the v0.1 substrate can't do it AND a measured ≥10×/significant-pp unlock.

## 3. The team (subagents) → LOGOS roles
`~/.claude/agents/`: **claude-architect** (HTN planner), **claude-worker** (implementer), **codex** (implementer/security/QA + independent verifier → `mcp__codex__codex`), **gemini** (research/validation/tie-break → `mcp__gemini__ask`). These are the dev-time team AND the candidate-generator/verifier pool for best-of-3.

## 4. Top risks (mitigations baked in)
1. **Reward hacking / test leakage (HIGHEST)** → three-tier split; harness-computed acceptance on hidden tests; audit visible-suite mutation score.
2. **Infinite loops on hallucinated files** → rollback-on-repetition + file/function existence check (budget alone is insufficient).
3. **Context explosion** (the thing we claim to fix) → short cycles + context reset + ledger re-read + ECP. If the curve doesn't flatten, the thesis is unproven — report it.
4. **Underpowered/p-hacked eval** → n≥20, ≥3 seeds, paired t-test/Mann-Whitney-U, p<0.05, 95% CIs. Honest negatives required.
5. **Training-data contamination** → verify commit dates; trust the within-harness DELTA, not absolute %.
6. **Sandbox privilege** → docker-group≈root; run containers `--user` non-root, `--cap-drop=ALL`, `--network=none`.
7. **Single-auditor drift** → Gemini back online; triad review on execution-layer code too.
8. **Over-engineering toward formal HTN/ATMS/SMT** → `NOT_IN_V0_1.md` is the gate.

## 5. Founder gate (only one)
Add `neo` to the docker group (root-equivalent — accepted given Tailscale-only / Lynis-87 / agents don't get it) + one session restart so the harness inherits the group. Everything else is autonomous-with-evidence under GAEO.
