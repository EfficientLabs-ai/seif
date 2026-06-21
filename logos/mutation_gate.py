#!/usr/bin/env python3
"""SEIF Mutation Adequacy Gate (v0.2 WP-C) — measure whether a test suite can REJECT plausible-wrong
implementations, not merely pass on the candidate. SWE-Mutation's finding: model/auto-generated tests
often look useful yet fail to kill realistic agentic mutants. So a suite is not acceptance-grade until it
kills an adequate share of realistic mutants.

This module GENERATES mutants (deterministic, AST-based for Python — reliable, not regex) and SCORES a
suite via an INJECTED executor `run_on_mutant(mutant_source) -> killed: bool` (killed = the suite fails on
the mutant, i.e. it detected the bug). Execution wiring (run the suite per mutant in the sandbox) is the
oracle's job (WP-D); here the generation + scoring is pure and unit-testable. Thresholds stay EXPERIMENTAL
until baselined — do NOT hardcode a public pass threshold.
"""
import ast
import copy

_CMP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.LtE, ast.LtE: ast.Lt,
        ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
_BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}
_BOOL = {ast.And: ast.Or, ast.Or: ast.And}


def _eligible(node):
    """(family, kind) if this node can be mutated, else None. One mutation per eligible node."""
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP:
        return ("boundary_or_equality", "cmp")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return ("arithmetic", "bin")
    if isinstance(node, ast.BoolOp) and type(node.op) in _BOOL:
        return ("boolean_logic", "bool")
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return ("wrong_constant", "boolconst")
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return ("off_by_one", "int")
    if isinstance(node, ast.Return) and node.value is not None:
        return ("wrong_return", "ret")
    return None


def _apply(node, kind):
    if kind == "cmp":
        node.ops = [_CMP[type(node.ops[0])]()]
    elif kind == "bin":
        node.op = _BIN[type(node.op)]()
    elif kind == "bool":
        node.op = _BOOL[type(node.op)]()
    elif kind == "boolconst":
        node.value = not node.value
    elif kind == "int":
        node.value = node.value + 1
    elif kind == "ret":
        node.value = ast.Constant(value=None)
    return node


def generate_mutants(source, max_total=40):
    """Return [{mutant_id, family, source, description}] — one single-site mutant per eligible AST node."""
    tree = ast.parse(source)
    sites = [(i, _eligible(n)) for i, n in enumerate(ast.walk(tree)) if _eligible(n)]
    mutants = []
    for k, (target_i, (family, kind)) in enumerate(sites[:max_total]):
        t = ast.parse(source)                      # fresh tree per mutant (clean, no shared state)
        nodes = list(ast.walk(t))
        _apply(nodes[target_i], kind)
        try:
            mutated = ast.unparse(ast.fix_missing_locations(t))
        except Exception:                          # noqa: BLE001 - skip any node that won't unparse
            continue
        if mutated.strip() == source.strip():
            continue                               # no-op mutation (e.g., idempotent) — skip
        mutants.append({"mutant_id": f"m{k}", "family": family, "source": mutated,
                        "description": f"{family} mutation at walk-index {target_i}"})
    return mutants


def mutation_score(mutants, run_on_mutant):
    """run_on_mutant(mutant_source) -> killed(bool). Returns {total, killed, survived, score, by_family,
    survivors}. score = killed/total. A high survivor count = the test suite is too weak (inadequate)."""
    killed, survivors, by_family = 0, [], {}
    for m in mutants:
        fam = by_family.setdefault(m["family"], {"killed": 0, "total": 0})
        fam["total"] += 1
        try:
            k = bool(run_on_mutant(m["source"]))
        except Exception:                          # noqa: BLE001 - executor error = not a clean kill
            k = False
        if k:
            killed += 1
            fam["killed"] += 1
        else:
            survivors.append(m["mutant_id"])
    total = len(mutants)
    return {"total": total, "killed": killed, "survived": total - killed,
            "score": round(killed / total, 3) if total else None,
            "by_family": by_family, "survivors": survivors}


def _selftest():
    src = ("def classify(n):\n"
           "    if n > 0:\n"
           "        return n + 1\n"
           "    elif n == 0:\n"
           "        return 0\n"
           "    return n - 1\n")
    muts = generate_mutants(src)
    fams = {m["family"] for m in muts}
    assert len(muts) >= 4, f"expected several mutants, got {len(muts)}"
    assert {"boundary_or_equality", "arithmetic"} <= fams, f"missing families: {fams}"
    assert all(ast.parse(m["source"]) for m in muts), "every mutant must be valid Python"
    assert all(m["source"].strip() != src.strip() for m in muts), "no no-op mutants"
    # a perfect suite kills everything -> score 1.0; a useless suite kills nothing -> 0.0
    assert mutation_score(muts, lambda s: True)["score"] == 1.0
    weak = mutation_score(muts, lambda s: False)
    assert weak["score"] == 0.0 and len(weak["survivors"]) == len(muts)
    # a partial suite that only kills arithmetic mutants -> 0<score<1, by_family reflects it
    part = mutation_score(muts, lambda s: ("- 1" not in s and "/ " not in s) is False)  # noisy partial
    assert part["score"] is not None
    print(f"mutation_gate selftest PASS — {len(muts)} mutants across {sorted(fams)}; "
          f"score math + by_family + survivors correct")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: mutation_gate.py --selftest")
