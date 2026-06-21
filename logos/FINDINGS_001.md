# LOGOS eval — Finding 001: naive execution-feedback underperforms the blind baseline

**Date:** 2026-06-21 · **Eval:** 20 SWE-bench-Verified instances (light repos: requests/pylint/pytest), 1 seed.
**Grading:** official `swebench` harness on held-out FAIL_TO_PASS/PASS_TO_PASS. Worker = `claude -p` (identical both arms).

## Result
| arm | resolved | rate | 95% CI (Wilson) |
|---|---|---|---|
| A — blind one-shot | 14/20 | 70.0% | [48.1, 85.5] |
| B — LOGOS execution-feedback (self-authored repro + stop-on-green) | 11/20 | 55.0% | [34.2, 74.2] |

- **Delta: −15.0 pp (B worse).** McNemar exact **p = 0.25** → **NOT significant** at n=20, 1 seed.
- **B's resolved set is a strict SUBSET of A's.** B won nothing A didn't; B lost exactly 3:
  `pylint-dev__pylint-6386`, `pylint-dev__pylint-8898`, `pytest-dev__pytest-5840`.
- Degradation curve: single 9/12 vs 9/12 (tie); multi 4/6 vs 2/6; large 1/2 vs 0/2 — B's loss concentrates on the **harder, multi-file** tasks.

## Mechanism (evidence-backed)
All 3 discordant losses share one signature: **`steps=1, repro_pass=True`, and B's patch is SMALLER than A's**:
| instance | A patch | B patch | B stopped |
|---|---|---|---|
| pylint-6386 | 1299 b | 971 b | step 1, repro pass |
| pylint-8898 | 2802 b | 2567 b | step 1, repro pass |
| pytest-5840 | 3814 b | 1574 b | step 1, repro pass |

Concrete (pytest-5840): the bug is `unique_path` lower-casing paths via `normcase`, breaking conftest
loading on case-insensitive filesystems. **A** re-keyed conftest caching by `Path(...).resolve()` across
`_pytest/config/__init__.py` AND `pathlib.py` (the real fix). **B** only patched `unique_path` in
`pathlib.py`; its self-authored repro exercised that helper in isolation, passed, and B stopped — but the
held-out test grades the full conftest-loading path B never touched.

**Conclusion:** a self-authored reproduction is a *necessary-not-sufficient* signal. The agent scopes the
repro to the fix it has in mind; a partial fix passes it; the loop reads green as "done" and ships a
narrower patch than the careful one-shot. **Stop-on-green creates false-positive stops.** This is not a
harness fault (scorer credits gold, rejects partial) and not statistically proven (p=0.25) — but the
direction + the monotone-subset pattern + the identical per-loss signature make it a real, actionable lead.

## Why this is the right kind of result
This is the build→test→find-issue→iterate loop working. A naive single-signal feedback loop HURTS — which
is precisely the motivation for the full LOGOS machinery (independent verification, best-of-N, not trusting
one signal). The negative result is more useful right now than a lucky positive would have been.

## Arm B v2 — candidate fixes to test next (isolate one variable at a time)
1. **Kill stop-on-green.** Never stop just because the self-authored repro passes; always run the full
   step budget, and make the agent CRITIQUE its own fix for completeness vs the *whole* issue
   ("does this handle every case the issue describes, or only the one in my repro?") before finalizing.
2. **Independent completeness verifier as the stop gate** (the LOGOS "Claude builds → Codex verifies"
   pattern, in-loop): Codex must sign off that the fix is complete for the issue, not just repro-passing.
3. **Broaden the feedback signal:** run the repo's existing *related* test modules (regression), not only
   the agent's one repro — a narrow fix that breaks/under-covers real behavior gets caught.
4. **best-of-N candidates** (LOGOS best-of-3): generate multiple fixes, select by strongest verification —
   a comprehensive fix should beat a narrow one.

Recommended first v2 experiment: **(1)+(2)** — remove early-stop and add an independent completeness gate —
the smallest change that directly targets the measured pathology. Re-run the same 20, same seed, compare.

## Arm B v2 — smoke result (2026-06-21, pytest-5840, the instance v1 lost)
Built v2 = kill stop-on-green + independent Codex completeness gate (`swe_arm_b_v2.py`, Codex-reviewed).
On pytest-5840 the **mechanism worked as designed**: step 1 the agent shipped the same narrow fix v1
did, the gate returned **INCOMPLETE** naming the exact gap ("no `self._conftest_plugins`/module-cache
invalidation for mixed-case names"), step 2 the agent expanded the fix, gate returned **COMPLETE**.
Patch grew **1574 b (v1) → 4122 b (v2)** (A was 3814 b). **No PASS_TO_PASS regression.**
**BUT still UNRESOLVED:** both FAIL_TO_PASS (`test_setinitial_conftest_subdirs[test|tests]`) still fail.
**Lesson:** an LLM completeness gate is NOT a ground-truth oracle — "complete per the issue text" can
still miss the exact graded behavior. The gate fixes the *false-positive-stop*; it does not guarantee the
gold approach. Whether v2 beats v1 / approaches A is an **aggregate** question — full 20-instance v2 batch
running; `analyze.py` now reports A vs v1 vs v2 with A-vs-v2 and v1-vs-v2 McNemar pairs.

## Finding 002 — the independent gate recovers the regression and edges past blind (2026-06-21)
Full 20-instance v2 batch (same clone, same scorer, 1 seed):

| arm | resolved | rate | 95% CI (Wilson) |
|---|---|---|---|
| A — blind one-shot | 14/20 | 70.0% | [48.1, 85.5] |
| B v1 — feedback + stop-on-green | 11/20 | 55.0% | [34.2, 74.2] |
| **B v2 — feedback + independent completeness gate** | **15/20** | **75.0%** | [53.1, 88.8] |

McNemar (exact): **v1→v2 = +20pp** (v2-only=4, v1-only=0 — v2's resolved set is a STRICT SUPERSET of v1's,
p=0.125); **A→v2 = +5pp** (v2-only=2, A-only=1, p=1.0); A→v1 = −15pp (the original regression).
Degradation curve: single 9/9/**11** · multi 4/2/3 · large 1/0/1 (A/v1/v2).

**Reads (honest):**
1. The gate **fixed the v1 pathology**: v2 strictly dominates v1 (+20pp, never lost an instance v1 won).
   Independent completeness verification directly removed the false-positive-stop.
2. **v2 is the best arm and the only one to beat blind (75% vs 70%)** — but +5pp at n=20/1-seed is a
   statistical TIE (p=1.0; net +1 instance: v2 won pylint-4970 & 7080 that blind missed, lost pylint-8898).
3. **Nothing is significant at n=20, 1 seed.** Direction + the strict-superset pattern are the signal.
4. Stochasticity note: pytest-5840 (unresolved in the v2 smoke) RESOLVED in the batch re-run — per-instance
   runs are stochastic; another reason seeds matter.

**Confound (state honestly):** v2 uses more compute than A (multi-turn + a Codex judge). The clean
gate-isolating comparison is **v1 vs v2** (both multi-turn-capable; v2 adds the gate) → +20pp. A-vs-v2 is
the full-pipeline-vs-blind comparison.

**Next for a publishable claim:** 3 seeds × 20 (kills stochastic noise), then more instances + heavier repos.
Optional ablation: "multi-turn feedback, no gate" to separate extra-turns from the gate itself.

## Finding 003 — the result holds at n=37 (2026-06-21)
Scaled to all 37 light-repo instances (superset of the 20), official scorer, 1 seed:

| arm | resolved | rate | 95% CI (Wilson) |
|---|---|---|---|
| A — blind | 28/37 | 75.7% | [59.9, 86.6] |
| v1 — feedback + stop-on-green | 26/37 | 70.3% | [54.2, 82.5] |
| **v2 — feedback + independent gate** | **30/37** | **81.1%** | [65.8, 90.5] |

McNemar (exact): **v1→v2 = +10.8pp** (v2-only=4, v1-only=0 — STILL a strict superset, p=0.125);
**A→v2 = +5.4pp** (v2-only=3, A-only=1, p=0.625); A→v1 = −5.4pp.

**Robust reads (what survived doubling n):**
1. **v2 strictly dominates v1 at n=37 too** (superset, +10.8pp). The independent gate's value is robust — this is the load-bearing, repeatable finding.
2. **v2 is the best arm and beats blind by ~5pp at BOTH n=20 (+5.0) and n=37 (+5.4)** — consistent direction, still NOT significant (p=0.625). A ~5pp effect needs ~100+ instances; expected.
3. **Honesty correction to Finding 001:** v1's dramatic n=20 crash (55%) was partly small-sample noise — at n=37 naive feedback is 70.3% (−5.4pp vs blind, not −15). The robust claim is "self-check ≤ blind, and the **gate > both**," NOT "naive feedback craters."
4. Degradation curve still unreadable: multi (n=6) / large (n=2) buckets too small — needs heavier repos (roadmap P2), as flagged.

**Defensible claim now:** *"An independent completeness gate strictly dominates naive self-verification (+10.8pp, strict superset, robust across n=20 and n=37) and holds a consistent ~5pp edge over blind one-shot — not yet statistically significant (p=0.625); significance needs 3 seeds + ~100 instances."*

## Finding 004 — the MOAT-DECIDER: it's the gate, not the turns (2026-06-21)
No-gate ablation (arm_b_v3_nogate = identical multi-turn execution-feedback loop, full budget, but NO
independent gate), 37 instances, 1 seed, official scorer:

| arm | resolved | rate | 95% CI |
|---|---|---|---|
| A — blind one-shot | 28/37 | 75.7% | [59.9, 86.6] |
| v1 — feedback + stop-on-green | 26/37 | 70.3% | [54.2, 82.5] |
| v3 — feedback, NO gate (full budget) | 27/37 | 73.0% | [57.0, 84.6] |
| **v2 — feedback + INDEPENDENT gate** | **30/37** | **81.1%** | [65.8, 90.5] |

**The ordering is the result:** v2 (gate) > A (blind) > v3 (no-gate) ≈ A > v1 (stop-on-green).
- **v2 vs v3 = +8.1pp** (v2-only=5, v3-only=2, McNemar p=0.45). The independent gate is the active ingredient.
- **v3 ≈ blind** (73.0 vs 75.7): multi-turn execution feedback *without* an independent check does NOT beat
  blind. **More turns/compute alone doesn't help.** Only adding independent verification lifts above blind.
- **Not significant** at n=37/1-seed (every pairwise p ≥ 0.13). Direction + the clean ordering are the signal.

**Defensible claim (honest):** *"Execution feedback only helps when paired with INDEPENDENT verification.
Iterating more on the model's own signal (v3) lands at blind-parity; the lift to 81% comes specifically
from the independent completeness gate (+8.1pp over the same loop without it). Not yet statistically
significant — needs 3 seeds + ~100 instances."* This isolates the architectural lever: **externalized,
independent verification — not more model deliberation — is what works.** Exactly the Sovereign
Intelligence Amplification thesis (build what the model can't reliably provide itself).

## Reproduce
```
/home/neo/logos-venv/bin/python logos/analyze.py --score   # scores both arms, writes logs/AB_REPORT.md
```
Predictions in `logos/preds/{arm_a_,arm_b_logos_}<iid>.jsonl` (+ `.meta.json`). Report: `logs/AB_REPORT.md`.
