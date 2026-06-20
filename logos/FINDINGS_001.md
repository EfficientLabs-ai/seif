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

## Reproduce
```
/home/neo/logos-venv/bin/python logos/analyze.py --score   # scores both arms, writes logs/AB_REPORT.md
```
Predictions in `logos/preds/{arm_a_,arm_b_logos_}<iid>.jsonl` (+ `.meta.json`). Report: `logs/AB_REPORT.md`.
