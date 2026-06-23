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

## E3 — model routing (MEASURED)

Hold context constant (full env), vary ONLY the model across the same 3 tasks × 2 seeds. All three models
resolved **6/6 (100%)**, so cost-per-resolved equals cost-per-call here — an equal-quality comparison.

| Model | resolve | $/resolved | tokens | vs opus |
| --- | --- | --- | --- | --- |
| claude-opus-4-8 | 6/6 | **$0.625** | ~430K | — |
| claude-sonnet-4-6 | 6/6 | **$0.220** | ~232K | **−65%** (2.8×) |
| claude-haiku-4-5 | 6/6 | **$0.085** | ~293K | **−86%** (7.4×) |

**Model routing is a real, large cost lever — up to −86% at EQUAL resolve-rate.** (Pricing checks out:
haiku's lower per-token rate dominates even though it sometimes uses *more* tokens than sonnet.)

## Round 2a — routing frontier + escalation router (MEASURED, n=1/task)

Difficulty-graded set (2 easy + 3 textbook-hard algorithmic bugs: roman numerals, interval-merge,
balanced-brackets — each with multi-assertion/edge-case tests), each × {opus, sonnet, haiku}; plus an
escalation router (haiku → sonnet → opus, escalate on a failing test).

| Model | resolve (all) | $/resolved | hard-only resolve · $/resolved |
| --- | --- | --- | --- |
| opus-4-8 | 5/5 | $0.667 | 3/3 · $0.691 |
| sonnet-4-6 | 5/5 | $0.244 (−63%) | 3/3 · $0.251 |
| haiku-4-5 | 5/5 | **$0.105 (−84%)** | 3/3 · $0.111 |

- **The routing advantage holds across easy→textbook-hard.** Haiku resolved all three hard algorithmic
  bugs 100% — so the −84% advantage is robust well past trivial fixes. **The true capability frontier is
  *further out* than classic algorithms** (they're well-represented in every model's training); finding it
  needs genuinely novel / real-codebase complexity (→ E4).
- **Escalation router:** resolved 5/5, all at haiku → **$0.089/resolved (−87% vs opus)**; it never needed
  to escalate. The logic is validated, but its *rescue value* (catching a cheap-model miss) was not
  exercised because nothing failed here. That requires a task set haiku actually fails (→ E4).
- **Honest limits:** n=1 seed; "hard" = textbook algorithms, not novel/real-repo difficulty.

## What the real levers are

1. **Leaner per-call context** (don't re-send the whole environment every call) — MEASURED: fresh input
   −92% / ~$0.14/call env tax. "File architecture" in the truest sense; partly just context discipline.
2. **Model routing** (route work to the cheapest capable model) — MEASURED (E3 + Round 2a): −63%/−84% at
   equal resolve-rate, robust through textbook-hard algorithmic bugs; an escalation router gives −87% with
   an opus safety net. Capability frontier (where cheap models fail) is beyond classic algorithms → E4.
3. **NOT graph delta-scoping** — REFUTED (E2).

## Caveats (will not hide)

- MEASURED on **one machine, a controlled fixture, small n** — characterizes this environment, not a law.
  Real-codebase validation is a follow-up.
- Lead with **fresh-input tokens** and **dollars at a fixed model**; never quote cache-inflated raw totals.
- Resolve-rate / gate-quality is **not** claimed here (a nested-`claude` empty-output flakiness, handled
  in the benches via retry-on-empty, invalidated the earlier one-shot-vs-loop quality comparison).

## Recommended follow-ups (revealed by these measurements)

- **Production retry-on-empty**: the live loop's `_claude_edit` should retry a zero-token (empty) envelope
  rather than treating it as "no change → stop" (the flakiness wastes a budget step). Separate gated PR.
- **E3 model routing — DONE**; **Round 2a frontier + escalation router — DONE** (above): routing holds
  through textbook-hard; the capability frontier is beyond classic algorithms.
- **E4 — real-codebase validation** (next): run the levers on a real repo (larger files, novel logic) to
  (a) confirm the per-call composition + routing hold beyond the toy fixture and (b) actually reach the
  frontier where cheaper models fail — exercising the escalation router's rescue value. Add seeds for CIs.

Pricing used (verified live 2026-06-24, USD/MTok): Opus 4.8 — input $5, output $25, cache-write(5m) $6.25,
cache-read $0.50. Sonnet 4.6 — $3 / $15 / $3.75 / $0.30. Haiku 4.5 — $1 / $5 / $1.25 / $0.10.
