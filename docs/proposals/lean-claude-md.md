# Proposal (FOUNDER-GATED) — lean the global `~/.claude/CLAUDE.md`

**Status: proposal for founder decision. Not executed.** Editing `~/.claude/CLAUDE.md` is runtime
self-modification of the global environment — founder-only. This document is the *evidence + plan*; the cut
is yours.

## Why — the measured evidence

Round 3 (`docs/FINDINGS_LOAD_ARCHITECTURE.md`) decomposed the ~31.7K fresh-input tax that loads on **every**
`claude` call:

| Source | fresh tokens/call | share |
| --- | --- | --- |
| **user `CLAUDE.md` + skills + hooks** | **~17,000** | **~54%** |
| MCP tool schemas | ~13,600 | ~43% |
| irreducible base | ~2,500 | ~3% |

The user environment is the **single largest source**. The ECP route compiler already strips it for tasks
that accept the cheap default model (`--setting-sources project`), but that's a per-task workaround. The
durable fix is to make the global `CLAUDE.md` itself small, so *every* call — interactive included — pays
less.

> Anthropic's own guidance: keep root instructions concise; move scoped material to path-specific rules and
> skills. Splitting one big file into many *imported* files does **not** reduce tokens (imports still load) —
> the win is loading **less**, on demand.

## What to KEEP in `~/.claude/CLAUDE.md` (~50–150 lines)

Only universal invariants that genuinely apply to every session:
- Founder identity + the few hard safety rules (secrets never in output; never force-push/merge to main;
  commit attribution).
- The SEIF-gated-pipeline invocation rule (one line + a pointer).
- Where the routing manifests / reference live (pointers, not bodies).
- The tri-model default (one line).

## What to MOVE OUT (the ~17K)

- **Per-project / per-path detail → `.claude/rules/`** (loads only when working matching files) — e.g. repo
  routing tables, project-specific conventions.
- **Procedures/workflows → skills** (load on demand, not every session) — the capability map bodies, the
  detailed pipeline docs, the long playbooks currently inlined or always-referenced.
- **Historical lessons / doctrine → reference files** pulled in by route/skill when relevant, not globally.
- **Heavy reference tables** (capability map detail, etc.) → `reference/` loaded on demand (already the
  stated intent — enforce it).

## Expected effect + the honest constraint

- A lean global `CLAUDE.md` cuts the ~17K (~54%) from **every** call, interactive and headless — the biggest
  single lever, applied globally rather than per-task.
- **Measured constraint:** the per-task `--setting-sources project` path that ALSO captures this saving forces
  the cheap model. A lean *global* `CLAUDE.md` avoids that tradeoff — it shrinks the load **without**
  changing the model, so you can run opus interactively at the lower per-call cost. This is the main reason
  to do the global cut in addition to the route compiler.

## How to verify the cut (no guessing)

After the cut, re-run the load ablation (`logos/loadarch_bench.py`) — the `full` arm's fresh-input should
drop toward the `noUser` arm. The Context Bill of Materials (per-call `model_actual` + token classes,
already in receipts via PR #35) will show the realized per-call reduction on live runs. Report the measured
before/after; don't claim it until measured.

## Decision requested

1. Approve leaning `~/.claude/CLAUDE.md` to the kept-set above? (founder-only edit)
2. If yes: I'll draft the exact lean file + the `.claude/rules/` + skill moves as a reviewable diff for your
   approval before anything is applied — and re-run the ablation to measure the realized saving.
