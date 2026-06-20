# SEIF Evaluation — proving the long-horizon delta (HARNESS_C0)

**Goal:** empirically measure whether SEIF reduces the well-known drop in frontier-model performance over long, multi-layered tasks — with numbers we can **reproduce and publish**.

> Claim discipline: NO "100%". The deliverable is a measured, statistically-significant **delta vs. a controlled baseline**. An unreproducible number destroys the "prove your work" wedge. Honesty is the moat.

## The phenomenon (what we measure)
Quality decays as a run gets longer / more multi-layered (context degradation, hallucinated deps, premature termination, regressions in adjacent code). Long-horizon benchmarks make this visible — e.g. SWE-EVO (~25%) and SWE-Marathon (<30% on ultra-long tasks) per the SEIF verdict's cited arXiv sources **(re-verify against live leaderboards when we wire the harness — never cite from memory).**

## Hypothesis (the SEIF mechanism)
SEIF mitigates the drop by reducing reliance on a long, degrading context:
1. **State externalized** to the event ledger (model re-reads truth, doesn't re-derive it).
2. **ECP** compiles minimal, task-specific context per step (less rot surface).
3. **FSM task decomposition** bounds each step.
4. **Independent verification** (Codex/CodeRabbit/adversarial) catches drift the builder can't see.

## Design — controlled A/B (the real proof)
Same model, same tasks, same seeds; only the harness differs.
- **Arm A (baseline):** model alone in the benchmark's stock harness.
- **Arm B (SEIF):** same model + SEIF (ledger + ECP context packages + FSM gating + independent verify).
- **Substrate:** public, reproducible benchmarks — SWE-bench-Verified (multi-file), SWE-EVO (release-level), SWE-Marathon (ultra-long), Terminal-Bench. Start with ONE.
- **HARNESS_C0:** freeze the SEIF config (schemas, ECP weights, routing, prompts, verify thresholds) + hash it. Challengers (C1, C2…) only promote if they beat C0 with statistical significance.

## Metrics
| Metric | Why |
|---|---|
| FAIL_TO_PASS | did it actually resolve the objective |
| PASS_TO_PASS | did it avoid regressions in adjacent code |
| success vs. task-length / turn-count | **the degradation curve** — the headline plot (A vs B) |
| token efficiency (tokens / solved task) | the cost side of the flywheel |
| hallucinated-dependency rate | a direct degradation signal |
| premature-termination rate | long-horizon failure mode |

The proof is the **A-vs-B degradation curve**: if SEIF's curve stays flatter as tasks lengthen, the mechanism works — and that gap, with CIs, is the publishable claim.

## Two evidence tiers (don't conflate them)
- **Observational** — telemetry from real SEIF sessions (this one's ledger: rejected-transition rate, rework, contradiction rate over session length). Cheap, ongoing, suggestive — **not** controlled proof.
- **Controlled** — the A/B benchmark above. **This** is the proof. Only controlled numbers go in public claims.

## First slice (smallest credible experiment)
1. Pick ONE benchmark (recommend SWE-bench-Verified — best tooling) + a small N (e.g. 20 tasks).
2. Build the SEIF arm adapter (wrap the task as a SEIF task envelope → ledger → ECP context → FSM → verify).
3. Run A vs B on the same N; report FAIL_TO_PASS, PASS_TO_PASS, tokens, and the length-bucketed success curve with confidence intervals.
4. If B > A significantly → that's the first real proof. If not → SEIF gets enhanced (the HARNESS challenger loop) until it does, or we report honestly that it doesn't yet.

## Using the live account + this session
The active Claude Code session is the **first observational subject** — its SEIF ledger is the data. Treat session telemetry as a hypothesis generator; the controlled benchmark is what we publish. "Enhance SEIF to hit the goal" = the HARNESS_Cn challenger loop, gated on beating C0.

**Status:** VISION/design. Nothing measured yet. The first slice is a build, not a claim.
