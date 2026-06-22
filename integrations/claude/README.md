# Claude Code integration — the SEIF autonomous environment

These files bind Claude Code's autonomy primitives (`/loop`, `/goal`, hooks) to the SEIF gate so the
environment runs **loop/goal-driven** with the founder needed only at irreversible gates.

## The loop, composed
```
/seif-goal (one task) · /seif-loop (a backlog, on a cadence via native /loop)
        │  proposes
        ▼
LOGOS generate  ──►  logos/seif_run.py  (clean-room worktree, deps linked)
        │                    │ runs the project's REAL test suite (exit code = ground truth)
        ▼                    ▼
SEIF gate: tests pass  AND  integrity_guard clean  ── executable, unappealable
        │ ACCEPTABLE → branch + PR + receipt        │ REJECTED/no_change → rollback (ATMS) / retry / queue
        ▼                                            ▼
Tripartite Memory (L1 file→Redis / L2 episodic JSONL / L3 graphify)  ── STATE (never forgets)
        ▼
Codex independent verify  ·  founder_queue.jsonl  ·  Founder at the merge/secrets/production GATE
```
- **Gate** = the real test suite + the integrity guard (`logos/seif_run.py` + `logos/integrity_guard.py`).
- **State** = `memory/tripartite.py` + the receipts/ledger.
- **Stop** = `seif_run` budget + `/seif-loop` max-tasks + accept-rate floor + (always) the founder.

## What's autonomous vs founder-gated
- **Autonomous (already done, in `~/seif`):** the gate, the orchestrator, the memory layer, the trajectory
  summaries, and these command FILES. The loop generates PRs + receipts; it never merges.
- **Founder-gated (runtime self-modification — install yourself):**
  1. Copy the commands into your user config so they're invocable:
     `cp ~/seif/integrations/claude/commands/seif-*.md ~/.claude/commands/`
     (Custom commands are distinct from the native `/loop` and `/goal`; they wrap them with the gate.)
  2. To schedule a recurring cycle, run the native `/loop` with the body of `seif-loop.md` as its prompt,
     or invoke `/seif-loop <backlog.json>` on demand. A long-run cadence + a `Stop`-hook gate (block
     turn-completion until tests are green) are additional runtime-config changes — also founder-gated.
  3. L1 Redis (`apt install redis`, sudo) upgrades the working cache from the file fallback. Until then the
     file backend stands in automatically — no code change needed (`Memory().working.backend` reports which).

## Backlog format (`/seif-loop --backlog`)
A JSON list of:
```json
[{ "task_id": "stratos-routing-honesty",
   "repo": "/home/neo/StratosAgent",
   "task": "Add the routing-honesty test described in issue #1. Edit source only; do NOT edit tests.",
   "test_cmd": "node run-tests.mjs",
   "budget": 3 }]
```

## Safety invariants (enforced, not aspirational)
Never merge · never push to main · never edit tests/CI/the runner (integrity guard rejects it) · never touch
secrets/vault · honest status vocabulary (MEASURED/BUILT/WIRED/EXPERIMENTAL/TARGET) · "accepted" = tests +
integrity, proven by a receipt — not "merged"/"production".
