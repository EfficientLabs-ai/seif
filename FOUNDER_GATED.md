# Founder-Gated Queue — items needing Neo (review when back)

> Anything requiring secrets, a merge to main, production, publishing, or runtime self-modification is
> parked here per the deny-by-default doctrine. I (Claude) execute everything else autonomously and log
> it. Updated 2026-06-21 (founder at gym + Fortnite content; available remote).

## ✅ Cleared (2026-06-22)
- **SEIF PR #5 MERGED** (eval harness + Agent Harness + /seif + master architecture + v0.2 WP-A/C/E).
- **content-engine PR #2 MERGED** (claim-discipline gate + CI).
- **Gemini DEFERRED** by founder (can't auth; not worth the hassle). NOT a blocker — our roadmap already
  found the multi-model verifier *panel* overrated (correlated opinions); the independent-verifier role is
  **Codex-only**, and the real lever is executable evidence (the Evidence Engine). No Gemini dependency anywhere.

## ✅ Cleared (cont.)
- **SEIF PR #6 & #7 MERGED** (v0.2 Evidence Engine: WP-A..H + Governed Integration Fabric governance + docs).
- **FIRST REAL `/seif` TASK DONE END-TO-END:** StratosAgent **#2 (AGENTS.md governance) MERGED** via the
  full governed loop — `/seif` generated + verified (14/14) → I reviewed → **Codex caught an overclaim →
  fixed → Codex APPROVED** → merged → **issue #2 closed**. The stack operating on real EFL code, with a receipt.

## ⏳ Awaiting your call
| # | Item | Why gated | Action for you |
|---|---|---|---|
| 0 | **SEIF PR #8** — /seif driver bug-fixes (dep-symlink leak + gh -R slug) found dogfooding #2 | merge to main | review + merge: `gh pr merge 8 --squash` (EfficientLabs-ai/seif) |
| 1 | **Next `/seif` task** | you pick the work | StratosAgent #1 (routing-honesty tests) or #3 (release provenance), or a real bug anywhere — I run the full loop |
| 2 | **Composio (self-hosted) + Nango** for Stratos integrations | secrets/keys | provide keys when we reach P3 (Stratos-as-runtime); governance layer already built |
| 3 | **Hard branch protection** on EfficientLabs-ai/seif | org/plan | enable ruleset (already applied on content-engine) |
| 4 | **Publish/OSS decision** for SEIF (Apache) | public surface | hold until founder gate |
| 5 | **Social posting / content distribution** | public, brand | the poster stays gated; approve per-campaign |

## ✅ Done autonomously today (for your awareness)
- SEIF **action-ledger hook LIVE** (records every tool call, hash-chained, secrets redacted, fail-open).
- **P0 eval closed:** A 75.7% / v1 70.3% / **v2 81.1%** at n=37 (`logos/FINDINGS_001.md`).
- **Agent Harness** (eval-mode `logos/harness.py` + project-mode `logos/project_harness.py`) built + selftested.
- **EFL_OPERATING_SYSTEM.md** master architecture committed.
- content-engine **PR #1 merged** (content factory).

## 🤖 Executing autonomously tonight (no gate needed)
- ✅ `/seif` driver **built + Codex-safety-reviewed + PROVEN end-to-end** (synthetic repo: generate → real
  tests pass → landed on a branch → receipt; **main left untouched**). P1 functionally complete.
- ✅ Harness proven on **StratosAgent's real suite** — and the dogfood caught a real bug in MY harness
  (worktree missing gitignored deps); fixed (symlink dep dirs) + re-validated **14/14** (see correction below).
- ✅ **No-gate ablation DONE — MOAT-DECIDER answered:** A 75.7 / v1 70.3 / **v3-nogate 73.0** / **v2-gate 81.1**.
  It's the GATE, not the turns: multi-turn feedback WITHOUT an independent gate (v3) only reaches blind-parity
  (73 vs 75.7); the independent gate adds +8.1pp over the same loop. NOT significant at n=37/1-seed (direction
  + clean ordering only) — needs 3 seeds + ~100 instances. `logos/FINDINGS_001.md` Finding 004.
- I did **NOT** autonomously edit StratosAgent/ECP on an invented task — that's correctly yours to define (#3).
- Receipts/findings committed as I go; this file stays current.

## 🤖 v0.2 Evidence Engine — autonomous build progress (2026-06-22)
Per your binding v0.2 directive. Status legend honored (no confidence-upgrades).
- ✅ **3-seed significance scale-up LAUNCHED** (seeds 2,3 × 4 arms × 37, resumable; watcher auto-scores when done).
- ✅ **Research→Implementation matrix** (`docs/RESEARCH_TO_IMPLEMENTATION_MATRIX.md`) — every mechanism classified MEASURED/BUILT/WIRED/EXPERIMENTAL/TARGET/REJECTED.
- ✅ **WP-A Evidence Contract** (`logos/evidence_contract.py` + schema) — frozen/hashed proof obligations before any candidate; authenticity = ledger anchor (Codex-reviewed + hardened).
- ✅ **WP-E Integrity Guard** (`logos/integrity_guard.py`) — hard reward-hacking gate; Codex caught + I fixed 2 HARD bypasses (rename, quoted paths) + case-insensitivity. **This is the eval-integrity gate.**
- ✅ **WP-C Mutation Adequacy Gate** (`logos/mutation_gate.py`) — AST mutants + kill-rate scorer (do tests reject plausible-wrong impls?).
- ⏳ **NEXT (autonomous, in order):** WP-B candidate-blind Test Architect (needs an LLM), WP-D multi-channel Oracle (tri-state, wires A/C/E + harness), WP-F trajectory summaries, WP-G assumption graph, WP-H MCP telemetry; then the v0.2 experiments (equal-budget causality E, oracle-adequacy, 3-seed significance) + the required docs.
- All on PR #5's branch. NOT auto-merged. MCTS / new judges / auto-promotion NOT built (per directive).

## ⚠️ CORRECTION (integrity note)
My earlier "StratosAgent has 8 failing suites" was **WRONG — a harness artifact, now retracted.**
`git worktree` doesn't copy gitignored `node_modules`, so the worktree couldn't resolve `@noble/post-quantum`
and 8 suites crashed on import. **In the real repo StratosAgent passes 14/14.** Fixed the actual bug (in my
project-mode harness: it now symlinks dep dirs into the clean room) and re-validated 14/14 in a worktree.
Lesson logged: the dogfood correctly surfaced a real bug — in my tooling, not your agent — before `/seif`
could "fix" healthy code by deleting its PQC import. That's the discipline working.

## 📌 First decision when you're back
StratosAgent is **green**, so there's no failing suite to auto-target. Pick a **real `/seif` task** — a
genuine small feature or bug you want in StratosAgent (or another repo) — and I'll run the full loop
(generate → verify on real tests → branch/PR + receipt). I won't fabricate a task on healthy code.
