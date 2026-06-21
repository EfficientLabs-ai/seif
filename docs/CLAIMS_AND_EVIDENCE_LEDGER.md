# Claims & Evidence Ledger (binding — the only things we may say in public)

Date: 2026-06-22 · Rule: a row may be CLAIMED only at its stated scope with its cited evidence. Promotion
of a claim requires new evidence, never new confidence. "FORBIDDEN" phrasing must never appear.

## MEASURED — claimable now (with scope)
| Claim (exact wording) | Scope / caveat | Evidence |
|---|---|---|
| "An independent completeness gate strictly dominates naive self-verification (+10.8pp, a strict superset)." | light repos (requests/pylint/pytest), n=37, 1 seed | FINDINGS 001-003 |
| "It is the gate, not the turns: multi-turn feedback WITHOUT an independent gate (73.0%) only reaches blind-parity (75.7%); the gate lifts to 81.1% (+8.1pp over no-gate)." | n=37, 1 seed; **NOT statistically significant** (p≥0.13) — direction + clean ordering only | FINDINGS 004 |
| "Naive self-checking can make a model worse than blind one-shot." | the v1<A regression; magnitude was partly small-sample noise (n=20 −15pp → n=37 −5.4pp) | FINDINGS 001/003 |
| "Untrusted candidate code runs in a hardened, disposable sandbox with no host footprint." | docker net=none, caps dropped, tmpfs, ephemeral | `logos/sandbox.py` selftest |
| "Every agent action is recorded in a hash-chained, tamper-evident ledger." | metadata only; integrity (not authenticity) | `~/.claude/hooks/seif-ledger.py` |

## TARGET — may NOT be claimed yet (needs the cited evidence first)
| Aspiration | What unlocks it |
|---|---|
| "The gate beats blind one-shot." | A→v2 is +5.4pp, p=0.625 — needs ~100+ instances + ≥3 seeds (running) |
| "Flatter degradation curve / no context collapse." | a benchmark long enough to INDUCE collapse + measured slope m₀→m₁ with CIs (SWE-bench too short; need SWE-EVO/RoadmapBench) |
| "Independent EXECUTABLE evidence beats independent textual opinion." | the equal-budget causality experiment (Arm E vs D) — not yet run |
| any resolve-% as a capability number | pass@1 with seeds + CIs + cost/solve; pass@N only ever labeled "oracle upper bound" |

## FORBIDDEN phrasings (never ship)
"100% determinism / security / accuracy / retrieval" · "perfect verification" · "fully autonomous" ·
"mathematically proven ROI / cannot violate policy" · "perpetual self-improvement" · "eliminates context
collapse" · "premier provider / 1.3 Tbps / sub-40ms" (no traceroute/contract evidence) · "best-of-N is
MCTS" · "exit 0 means correct".

## Approved framings (use these)
"deterministic VERIFICATION of probabilistic generation" · "independent executable evidence" ·
"measured incremental yield" · "evidence-gated improvement" · "human-governed autonomy" ·
"explicit unknown states (INSUFFICIENT_EVIDENCE)" · "cryptographically verifiable execution history" ·
"model-independent capability amplification."
