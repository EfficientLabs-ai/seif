#!/usr/bin/env python3
"""SEIF graph-safety — REGRESSION-SAFETY over the code graph, NOT a token saver.

Honest claim discipline up front: this module has a MEASURED ~0% token effect. It does not shrink any
prompt or context window; it exists to stop a narrow change from silently breaking a dependent module by
telling the gate WHICH dependents' tests must re-run. The token economics of SEIF are settled elsewhere
(lean-context, model-routing); graph-safety is purely about not shipping a regression.

It is PURE composition over primitives that already exist — it adds no new state, owns no storage, and
DEGRADES GRACEFULLY (a missing graph yields None, never an exception):

  invalidation(repo, changed_files)  -> the dependent modules whose tests must re-run, i.e. the L3
                                        REVERSE-import closure of the changed files (memory/tripartite.py
                                        SemanticMemory.impact). "Change X → these depend on X → re-test them."
                                        None when the repo has no graph to answer from (cannot know),
                                        distinct from [] (knows: nothing depends on the change).

  test_selection(repo, changed_files) -> the minimal subset of TEST files to re-run for this change: the
                                        changed test files themselves PLUS the test files among the
                                        invalidation closure. None when the graph cannot answer — and a
                                        None here MUST make the caller fall back to the full suite, never
                                        skip testing. This is the data behind project_harness's OPTIONAL
                                        fast-path; the full suite stays the default and the final gate.

  blast_radius(repo, changed_files)  -> impacted symbols/files for the receipt — delegates verbatim to
                                        logos/delta_plan.py _blast_radius (single source of truth; do NOT
                                        duplicate the graph walk).

Dependency-free (stdlib + the existing SEIF primitives). delta_plan already puts logos/ and the sibling
memory/ on sys.path; importing it here makes SemanticMemory importable too.
"""
import os
import sys

# Reuse delta_plan's path wiring (it adds logos/ and the sibling memory/ to sys.path on import) and its
# _blast_radius — graph_safety must NOT re-implement the graph walk. Importing delta_plan is enough to
# make `tripartite` importable for the reverse-closure queries below.
_LOGOS = os.path.dirname(os.path.abspath(__file__))
_MEMORY = os.path.join(os.path.dirname(_LOGOS), "memory")
for _p in (_LOGOS, _MEMORY):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import delta_plan  # noqa: E402  (path wiring + the canonical _blast_radius we delegate to)


def _is_test_file(path):
    """A path is a test file if any path component starts with 'test' or ends in '_test.py'/'_test'.

    Covers the common Python layouts: tests/test_foo.py, test_foo.py, foo_test.py, a tests/ package dir.
    Deliberately conservative — false positives only ADD a test to the re-run set (safe), they never drop
    one. Matching is on the path the graph stores in `source_file`."""
    if not path:
        return False
    norm = path.replace("\\", "/")
    base = os.path.basename(norm)
    if base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py":
        return True
    # any directory component named like a test dir (tests/, test/) → treat files under it as tests
    parts = norm.split("/")
    for comp in parts[:-1]:
        if comp in ("tests", "test"):
            return True
    return False


def invalidation(repo, changed_files):
    """Dependent modules whose tests must re-run for `changed_files` — the L3 reverse-import closure.

    Wraps memory/tripartite.py SemanticMemory.impact via delta_plan._blast_radius (the single canonical
    reverse-closure walk). Returns a sorted list of source files that DEPEND ON the change ("what does
    changing these touch?"), or None when the repo has no graph / the graph is unreadable — None means
    'cannot know', which a safety-conscious caller must treat as 'fall back to the full suite', NOT [].
    """
    # delta_plan._blast_radius already: unions over changed_files, returns sorted, returns None on no/bad
    # graph and [] for 'graph present, nothing depends on the change'. Reuse it verbatim — do not duplicate.
    return delta_plan._blast_radius(repo, changed_files)


def test_selection(repo, changed_files):
    """Minimal subset of TEST files to re-run for `changed_files`, or None when the graph can't answer.

    The subset = (the changed files that are themselves tests) ∪ (the test files among the invalidation
    closure). Returned sorted + de-duplicated.

    CONTRACT for callers (project_harness fast-path): None here is the 'unknown' signal — the graph is
    absent/unreadable, so the safe action is to run the FULL suite, never to skip. A concrete list
    (possibly empty) means the graph answered; an empty list legitimately means 'no test directly exercises
    this change in the graph', but project_harness still defaults to the full suite unless the fast-path is
    explicitly enabled."""
    closure = invalidation(repo, changed_files)
    if closure is None:
        return None  # graph cannot answer → caller must fall back to the full suite, never skip
    selected = {p for p in (changed_files or []) if _is_test_file(p)}
    selected.update(p for p in closure if _is_test_file(p))
    return sorted(selected)


def blast_radius(repo, changed_files):
    """Impacted symbols/files for the receipt — delegates to delta_plan._blast_radius (single source of
    truth). Sorted list, [] when nothing is touched, None when the repo has no graph to answer from."""
    return delta_plan._blast_radius(repo, changed_files)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] in ("invalidation", "test_selection", "blast_radius"):
        import json
        fn = {"invalidation": invalidation, "test_selection": test_selection,
              "blast_radius": blast_radius}[sys.argv[1]]
        print(json.dumps(fn(sys.argv[2], sys.argv[3:] or None), indent=2))
    else:
        print("usage: graph_safety.py {invalidation|test_selection|blast_radius} <repo> [changed_file ...]\n"
              "  REGRESSION-SAFETY (measured ~0% token effect); full suite stays the default gate.")
