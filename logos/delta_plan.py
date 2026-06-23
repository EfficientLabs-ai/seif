#!/usr/bin/env python3
"""SEIF checkpoint-aware delta-planning CONTEXT — compose EXISTING primitives into a planner-ready dict.

A planner should plan a DELTA against the last known-good state, not from scratch every time. This module
assembles, from the primitives the loop already owns, the minimal context to do that:

  base          — the last HEALTHY L4 checkpoint (the branch-from / rollback target), or None.
  blast_radius  — the L3 reverse-import closure of the files about to change ("what does changing these
                  touch?"), unioned + sorted; None when the repo has NO graph to answer from.
  prior_lessons — L2 reusable lessons (accepted/gate_complete + a lesson) relevant to this task.
  prior_failures— L2 episodes for this task that already ended rejected/error (what NOT to repeat).

This is PURE composition: it adds no new state, owns no storage, and DEGRADES GRACEFULLY — a missing
checkpoint module, an absent/corrupt graph, or an empty episode log yields None/[] rather than an
exception, so a planner can ALWAYS call it. Dependency-free (stdlib + the existing SEIF primitives).
"""
import os
import sys

# checkpoint lives here in logos/; tripartite lives in the sibling memory/ dir. Put both on sys.path the
# same way tripartite puts logos/ on it for trajectory_summary — so this module imports cleanly however
# it is loaded (script, `from logos import delta_plan`, or a test that inserts only logos/ on the path).
_LOGOS = os.path.dirname(os.path.abspath(__file__))
_MEMORY = os.path.join(os.path.dirname(_LOGOS), "memory")
for _p in (_LOGOS, _MEMORY):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# L2 terminations that count as "this already failed" forensics for a task.
_FAILED_TERMINATIONS = ("rejected", "error")


def _base(repo):
    """Last healthy L4 checkpoint, or None. Never raises into the planner."""
    try:
        import checkpoint as CP  # noqa: E402  (logos/ on sys.path)
        return CP.last_healthy(repo) or None
    except Exception:  # noqa: BLE001 — module absent / unreadable registry → no base, never crash
        return None


def _blast_radius(repo, changed_files):
    """Reverse-import closure (L3) of the changed files, unioned + sorted. None when the repo has no graph
    to answer from (so a planner can tell 'nothing touched' [] apart from 'cannot know' None)."""
    try:
        from tripartite import SemanticMemory  # noqa: E402  (memory/ on sys.path)
        sm = SemanticMemory(repo)
        if not sm.available:
            return None
        radius = set()
        for path in (changed_files or []):
            radius.update(sm.impact(path))
        # impact() lazily loads the graph; a corrupt/unreadable graph flips `available` False DURING access
        # → we cannot actually know the blast radius, so report None (not an empty set = "nothing touched").
        if not sm.available:
            return None
        return sorted(radius)
    except Exception:  # noqa: BLE001 — tripartite absent / graph unreadable → cannot know
        return None


def _episodic(task_id):
    """(prior_lessons, prior_failures) from L2 for THIS task. Empty when task_id is None — an unscoped call
    must NOT pull global episodes from unrelated tasks into the planning context — or on any failure."""
    if task_id is None:
        return [], []
    try:
        from tripartite import EpisodicMemory  # noqa: E402
        em = EpisodicMemory()
        lessons = [r for r in em.reusable_lessons() if r.get("summary", {}).get("task_id") == task_id]
        failures = [r for r in em.query(task_id=task_id)
                    if r.get("summary", {}).get("termination_reason") in _FAILED_TERMINATIONS]
        return lessons, failures
    except Exception:  # noqa: BLE001 — store absent / unreadable → no episodic context, never crash
        return [], []


def delta_context(repo, changed_files=None, task_id=None):
    """Planner-ready delta-planning context for `repo`, composed from existing SEIF primitives.

    Returns {base, blast_radius, prior_lessons, prior_failures}. Pure + degrades gracefully: every field
    falls back (None / []) instead of raising, so this is always safe to call before planning."""
    lessons, failures = _episodic(task_id)
    return {
        "base": _base(repo),
        "blast_radius": _blast_radius(repo, changed_files),
        "prior_lessons": lessons,
        "prior_failures": failures,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--help":
        import json
        print(json.dumps(delta_context(sys.argv[1], changed_files=sys.argv[2:] or None), indent=2))
    else:
        print("usage: delta_plan.py <repo> [changed_file ...]   |   import: from logos import delta_plan")
