#!/usr/bin/env python3
"""SEIF Tripartite Memory CONTRACT — the single interface the three repos' memory layers should share.

Today memory exists THREE divergent ways (reconciliation, docs/EFL_ARCHITECTURE_AND_STRATEGY_ADDENDUM.md):
  • seif         — L1 file-KV + L2 episodic-JSONL + L3 graphify graph   (this repo, memory/tripartite.py)
  • StratosAgent — in-memory graph-query; "L1/L2/L3" are doc-context folders, not a memory hierarchy
  • Atmosphere   — LanceDB vector + FTS5 (not a graph)
…with "L1/L2/L3" meaning different things in each. This module is the **unification anchor**: one
language-agnostic SPEC of what each layer MUST expose, plus a `conforms()` checker for Python
implementations. It does NOT make the JS repos conform — it gives every repo ONE target to implement
against, and proves the seif facade already conforms (the others follow, tracked as TARGET).

Not a runtime dependency — a contract + a conformance check. Stdlib only.
"""

# Language-agnostic required surface per layer. JS repos implement the same names (camelCase ok there);
# `conforms()` checks Python objects. Keep this list MINIMAL — the shared core, not every convenience method.
CONTRACT = {
    "L1_working": ["set", "get", "delete", "keys"],          # + a `backend` attribute ('redis'|'file'|…)
    "L2_episodic": ["record", "query", "recent", "reusable_lessons"],
    "L3_semantic": ["impact", "dependencies", "path"],       # + an `available` attribute (graph present?)
    "facade": ["remember", "recall", "record_attempt", "graph", "continuity_snapshot"],
}


def _missing_methods(obj, names, label):
    return [f"{label}.{n}" for n in names if not callable(getattr(obj, n, None))]


def conforms(memory, *, working=None, episodic=None, semantic=None):
    """Check a Python memory facade against CONTRACT. Returns (ok: bool, missing: list[str]).

    `memory`   = the facade (must expose CONTRACT['facade']).
    `working`  = the L1 layer (defaults to memory.working).
    `episodic` = the L2 layer (defaults to memory.episodic).
    `semantic` = an L3 graph VIEW (e.g. memory.graph(repo)); optional — if omitted, L3 is not checked here
                 (the facade's `graph` method is still required and checked).
    Attribute requirements (`backend` on L1, `available` on L3) are checked when the layer is present.
    """
    missing = []
    missing += _missing_methods(memory, CONTRACT["facade"], "facade")

    w = working if working is not None else getattr(memory, "working", None)
    if w is None:
        missing.append("L1 (working) layer absent")
    else:
        missing += _missing_methods(w, CONTRACT["L1_working"], "L1")
        if not hasattr(w, "backend"):
            missing.append("L1.backend (attribute)")

    e = episodic if episodic is not None else getattr(memory, "episodic", None)
    if e is None:
        missing.append("L2 (episodic) layer absent")
    else:
        missing += _missing_methods(e, CONTRACT["L2_episodic"], "L2")

    if semantic is not None:
        missing += _missing_methods(semantic, CONTRACT["L3_semantic"], "L3")
        if not hasattr(semantic, "available"):
            missing.append("L3.available (attribute)")

    return (not missing, missing)


# ---------------- self-test ----------------
def _selftest():
    import os
    import sys
    import tempfile
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tripartite import Memory, WorkingMemory, EpisodicMemory  # noqa: E402

    tmp = tempfile.mkdtemp(prefix="t-contract-")
    mem = Memory()
    mem.working = WorkingMemory(path=os.path.join(tmp, "w.json"))
    mem.episodic = EpisodicMemory(path=os.path.join(tmp, "ep.jsonl"))
    g = mem.graph(os.path.join(tmp, "norepo"))                 # an L3 view (unavailable graph is fine)

    ok, missing = conforms(mem, semantic=g)
    assert ok, f"seif Memory must satisfy the contract; missing={missing}"

    # negative: an object missing methods is reported, not silently passed
    class Half:
        def remember(self): pass
    ok2, missing2 = conforms(Half())
    assert not ok2 and missing2, "incomplete impl must fail conformance"

    print("memory contract selftest PASS — seif Memory conforms; incomplete impls are flagged")
    print(f"  contract layers: { {k: len(v) for k, v in CONTRACT.items()} }")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: contract.py --selftest   |   import: from memory.contract import CONTRACT, conforms")
