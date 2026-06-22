---
description: Pursue ONE bounded goal through the SEIF gate until verified-or-budget — clean-room → real tests → integrity gate → PR + receipt → Codex review → founder queue. Never merges. $ARGUMENTS = the goal.
---

# /seif-goal — one bounded objective, verified or honestly stopped

Pursue exactly one objective: **$ARGUMENTS**. Same thesis as the loop — the model proposes; the project's
real tests + the integrity guard dispose; nothing auto-merges. This is the single-task form; use it for a
specific feature/bug rather than a backlog sweep.

## What to do

1. **Scope it.** Identify the target `repo`, the exact `test_cmd` (the project's real suite — exit code is
   ground truth), and a precise task description that ends with "Edit the source only; do NOT edit tests."
   If the goal is ambiguous or needs a decision only the founder can make, **stop and ask** — do not invent scope.

2. **Recall before acting.** From `~/seif`: `from memory.tripartite import Memory; m=Memory()` →
   `m.episodic.query(task_id=...)` for prior attempts, and `m.graph(repo).impact(<file>)` for blast-radius.
   Fold prior lessons into the task text so you don't repeat a dead end.

3. **Run the gate:**
   `cd ~/seif && python3 logos/seif_run.py --repo <repo> --task "<task>" --test "<test_cmd>" --budget 3`
   This clean-rooms a worktree, lets the model edit, runs the REAL tests, enforces the integrity guard, and
   on success lands a branch + opens a PR + mints a receipt. On failure it rolls back (ATMS) — main untouched.

4. **Independent verify (Codex).** If a PR landed, run `mcp__codex__codex` (read-only) on the diff. Real
   issue → fix-and-re-verify within budget, or annotate. **Never merge to make a problem go away.**

5. **Report the honest outcome:** VERIFIED (receipt h=…, PR url, blast-radius) or NOT-VERIFIED (reason:
   tests / integrity_violation / no_change / budget) — and what you'd try next. Queue the founder if a PR
   landed (`~/seif/FOUNDER_GATED.md`).

## Hard rules (unappealable)
- **Never merge. Never push to main. Never edit tests/CI/the runner. Never touch secrets/vault.** PRs only.
- **Budget is a hard ceiling.** At budget end with no clean pass, stop and report NOT-VERIFIED honestly —
  do not relax the gate, weaken the tests, or claim partial success as success.
- **Honesty vocabulary** (MEASURED/BUILT/WIRED/EXPERIMENTAL/TARGET). "Verified" = tests pass + integrity
  clean (receipt), not "merged"/"production".

## ultracode
With **ultracode**: generate several independent candidate approaches, gate each, and keep the one that
passes with the smallest blast-radius; add an adversarial Codex pass that actively tries to refute the fix.
Never merge; always queue the founder.
