# Findings — SEIF Token Economics (MEASURED, 2026-06-24)

Measured natively in our own Claude Code environment with real `claude -p` calls, via the metering
primitive `logos/usage_meter.py` and the controlled benches `logos/token_bench.py` (baseline) and
`logos/e1e2_bench.py` (E1 cost lever + E2 graph go/no-go). Raw artifacts in `docs/receipts/`.

Honesty vocabulary: **MEASURED** (verified), **COMPUTED** (derived from measured token counts × verified
pricing), **REFUTED** (hypothesis tested and rejected), **TARGET** (not yet proven).

## Headline

1. **The dominant token cost is fixed per-call environment overhead, not task work.** ~93% of a successful
   fix call is cached environment (this box's user `CLAUDE.md` + skills + hooks + MCP); only ~33K tokens is
   the actual reasoning.
2. **Leaning the per-call environment cuts fresh (full-price) input ~92%** — MEASURED at n=6
   (full=opus vs lean): mean **31,043 → 2,525 tokens/call**. Confirmed **same-model** (opus in both arms)
   in the clean pair (`docs/receipts/...-lean-clean.json`, `fix_shout`: 31,681 → 2,498 = −92.1%); the
   reduction is model-independent because input-token *counts* are ~invariant across models, not a pricing
   effect. COMPUTED env tax avoided ≈ **$0.14/call** (≈28.5K × $5/MTok opus input), plus the cache-write
   of that env.
3. **Graph context-scoping does NOT save tokens — REFUTED.** Even with the *correct* (forward-dependency)
   direction, telling the model the failing test's dependency closure changed fresh-input tokens by
   **0.5% (ratio 0.99, n=4, same model)** — i.e. nothing. The model already self-navigates.

## E1 — cost lever (full vs lean environment)

- **fresh input −91.9% (n=6).** full ≈ 31,043 → lean ≈ 2,525 tokens/call. In this E1 run the lean arm ran
  haiku (see below), so `n_clean_pairs=0` for the *cost ratio* — but the fresh-input *count* reduction is
  model-independent (token counts ~invariant across models) and is independently confirmed same-model
  (opus/opus) in the `lean-clean` receipt (`fix_shout`: 31,681 → 2,498 = −92.1%).
- **No clean same-model cost ratio.** `--setting-sources project` (what makes the call lean) also forces
  a silent model downgrade to `claude-haiku-4-5` in agentic mode that neither `--model` nor `--settings`
  overrides. So the lean arm ran haiku in all 6 pairs → 0 same-model pairs → the cost *ratio* is
  confounded and is not reported. The honest cost figure is therefore **COMPUTED, not ratio'd**.
- Combined lean+haiku cost was ~$0.15–0.20 vs full opus ~$0.58–0.72 (~75% cheaper) — but that bundles
  two levers (leaner context **and** a cheaper model) and must not be attributed to either alone.

## E2 — does graph scoping save tokens? (forward-dep vs free navigation, multi-hop bugs, same model)

| metric | scoped / free | reading |
| --- | --- | --- |
| fresh input | **0.99** | no real saving — the decisive number |
| total tokens | 0.62 | cache-driven, misleading |
| cost | 0.82 | ~18% — but mostly cheap cache-read |
| cost excl. cache-read (real-money floor) | 0.95 | only ~5%, and fresh input is unchanged |

**Verdict: REFUTED as a token lever.** `delta_context` / blast-radius should be repositioned as a
**regression-safety** feature (what to re-test), not a token-savings feature. (It is also reverse-import
and built-but-not-wired — see the architecture review.)

## What the real levers are

1. **Leaner per-call context** (don't re-send the whole environment every call) — the big, MEASURED lever.
   This is "file architecture" in the truest sense; partly it is just context discipline most setups skip.
2. **Model routing** (easy work → cheaper model) — real and obvious, but **not yet isolated**; the only
   cheaper-model data here came from the accidental haiku downgrade (confounded). TARGET: a deliberate,
   quality-controlled routing A/B (cost-per-*resolved*, not per-call).

## Caveats (will not hide)

- MEASURED on **one machine, a controlled fixture, small n** — characterizes this environment, not a law.
  Real-codebase validation is a follow-up.
- Lead with **fresh-input tokens** and **dollars at a fixed model**; never quote cache-inflated raw totals.
- Resolve-rate / gate-quality is **not** claimed here (a nested-`claude` empty-output flakiness, handled
  in the benches via retry-on-empty, invalidated the earlier one-shot-vs-loop quality comparison).

## Recommended follow-ups (revealed by these measurements)

- **Production retry-on-empty**: the live loop's `_claude_edit` should retry a zero-token (empty) envelope
  rather than treating it as "no change → stop" (the flakiness wastes a budget step). Separate gated PR.
- **Model routing experiment** (E3) and **real-repo validation** (E4) to convert the TARGET levers to
  MEASURED, with confidence intervals.

Pricing used (verified live 2026-06-24, USD/MTok): Opus 4.8 — input $5, output $25, cache-write(5m) $6.25,
cache-read $0.50. Haiku 4.5 — $1 / $5 / $1.25 / $0.10.
