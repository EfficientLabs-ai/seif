---
description: Run the SEIF-gated autonomous loop over a backlog — generate → real tests → integrity gate → PR + receipt → Codex review → founder queue. Never merges. $ARGUMENTS = backlog path or inline goal.
---

# /seif-loop — the autonomous engine (you are the engine; the founder stays the gate)

You are running the Efficient Labs autonomous loop. The thesis, in force: **the model proposes; the
project's own test suite (exit code) + the integrity guard dispose; nothing auto-merges.** You remove the
founder as the *engine*, never as the *gate* (merge / secrets / production / "is this actually good").

## What to do

1. **Resolve the backlog.** If `$ARGUMENTS` is a path to a JSON list of task dicts, use it. Otherwise treat
   `$ARGUMENTS` as a single goal and build a 1-item backlog. Each task dict:
   `{ "task_id", "repo", "task", "test_cmd", "budget"?, "protected"?, "lesson"? }`.
   The `task` text MUST say "Edit the source only; do NOT edit tests."

   ALWAYS use the **`logos-venv`** interpreter (`/home/neo/logos-venv/bin/python`) for every SEIF python
   command below — it has the Redis client, so L1 Tripartite Memory runs on **Redis** (bare `python3` lacks
   it and silently falls back to the file backend).

2. **Pull memory context first** (continuity, never re-derive from chat): from `~/seif`, run a quick snippet
   `/home/neo/logos-venv/bin/python -c "import sys; sys.path.insert(0,'memory'); from tripartite import Memory; print(Memory().continuity_snapshot())"`
   to see recent episodes + reusable lessons + L1 backend (expect `redis`). Fold prior lessons for this `task_id` into the task text.

3. **Drive the gate deterministically:**
   `cd ~/seif && /home/neo/logos-venv/bin/python logos/seif_loop.py --backlog <file> --max-tasks N --budget 3 --min-accept-rate 0.34`
   This runs each task through `seif_run` (clean-room → real tests → integrity guard → branch/PR + receipt),
   records a trajectory summary to episodic memory per attempt, enforces caps + the accept-rate floor, and
   appends every **landed** PR to `~/seif/kernel/ledger/founder_queue.jsonl`. It will **stop early** if the
   accept rate falls below the floor — do not override that; a failing loop should bail, not burn the backlog.

4. **Independent verify each landed PR with Codex** (the standing tri-model loop): for every PR in the
   founder queue from this cycle, run `mcp__codex__codex` (read-only) on the diff. If Codex flags a real
   issue, either fix-and-re-verify within budget or annotate the queue entry — **never merge to resolve it.**

5. **Report, then stop.** Print the cycle summary (attempted / accepted / landed / accept_rate /
   stopped_reason), the per-PR Codex verdicts, and the blast-radius (L3 impact) for each landed change.
   Update `~/seif/FOUNDER_GATED.md` with anything needing the founder.

## Hard rules (unappealable)
- **Never merge. Never push to main. Never edit tests/CI/the runner.** The integrity guard enforces the last
  one; you enforce the first two. PRs only.
- **Never touch secrets / `.env` / vault files.** No `bash -x` on anything that sources a vault.
- **Honesty vocabulary:** MEASURED / BUILT / WIRED / EXPERIMENTAL / TARGET. "Accepted" means tests passed +
  integrity clean (receipt proves it) — it does NOT mean "merged" or "production". Never claim otherwise.
- **Caps are real:** respect `--max-tasks`, per-task `--budget`, and the accept-rate floor. When the cycle
  stops, stop — do not silently start another.

## ultracode
When the founder ran this with **ultracode**, scale up: run a larger backlog, use parallel subagents for
the per-PR Codex reviews and for independent blast-radius analysis, and add a completeness pass ("what task
did the loop skip, what PR is unreviewed?"). Token cost is not the constraint; correctness + coverage are.
Still: never merge, never edit tests, always queue the founder.
