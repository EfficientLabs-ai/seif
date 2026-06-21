# v0.2 Experiment Pre-Registration

Date: 2026-06-22 · Pre-registered BEFORE running, so results can't be cherry-picked post-hoc. Any deviation
is recorded as an amendment with a reason. Grading = the official `swebench` harness on held-out
FAIL_TO_PASS/PASS_TO_PASS (never self-reported); reward-hacking guard = `integrity_guard` (regression set
disjoint from graded). Worker model = `claude -p` (Gemini deferred; independent verifier = Codex).

## Experiment 1 — equal-budget causality (the core question)
**Question:** does INDEPENDENT EXECUTABLE evidence beat extra turns and independent textual opinion?
**Arms (identical model, token budget, turn budget, wall-clock, tool access):**
- A: blind one-shot
- B: self-authored reproduction, stop-on-green
- C: same turns + execution feedback as v2, NO independent gate
- D: feedback + independent **textual** gate (Codex) — the current v2
- E: feedback + candidate-blind **executable** tests (WP-B Test Architect + WP-D Oracle)
**Primary metric:** resolved (official scorer), pass@1. **Secondary:** false-accept rate, cost/solve.
**Set:** the 37 light instances. **Seeds:** ≥3 (in progress via `run_seeds.py`).
**Stat test:** exact McNemar (paired, per instance×seed); Wilson CIs; repo-stratified bootstrap.
**Decision rule:** claim "executable evidence > textual gate" only if E>D with non-overlapping direction
across seeds AND McNemar p<0.05. Otherwise report the honest null.

## Experiment 2 — oracle adequacy
**Question:** does adding evidence channels make the verifier MORE trustworthy (fewer false accepts)?
**Arms (same candidates):** E1 blind unit tests · E2 +property/metamorphic · E3 +mutation adequacy
(WP-C) · E4 +differential · E5 full multi-channel oracle (WP-D).
**Primary new metrics:** false_accept_rate, false_reject_rate, mutation_score, hidden_test_transfer,
requirements_coverage, evidence_channels_passed. Resolve rate alone CANNOT show verifier trust.

## Experiment 3 — multiple seeds (significance, running now)
≥3 deterministic runs of A/v1/v2/v3 over the 37 set (`logos/preds/seed{1,2,3}/`). Report per-seed rate,
mean±SD, pooled exact McNemar, Wilson, repo-stratified bootstrap, cost + latency per verified solve.

## Experiment 4 — horizon generalization (AFTER v0.2 stable)
Heavier repos + more multi-file tasks + SWE-EVO / RoadmapBench / SWE-Marathon-style. Headline (only when
measured): "degrades more slowly as task horizon increases." A flat curve on a too-short benchmark is a
FINDING, not a win.

## Frozen reporting set (report ALL, not just resolve rate)
resolve (pass@1) · pass@N (labeled oracle upper bound) · false-accept · false-reject · mutation_score ·
empty-patch rate · timeout rate · harness-error rate · repro false-positive rate · gate false-positive
rate · human-escalation rate · cost/solve · latency/solve · per-seed + per-repo breakdown + CIs.
