#!/usr/bin/env python3
"""SEIF Evidence Contract (v0.2 WP-A) — compile a task into FROZEN, HASHED proof obligations BEFORE any
candidate is generated. The contract is the new stopping rule:

    all mandatory obligations have passing evidence  AND  no protected invariant failed
    AND  no unresolved dependency remains            (NOT "the model's reproduction turned green")

Candidate generation must NOT mutate the contract — `freeze()` stamps a content hash and
`verify_unmutated()` detects any later tampering. Validation is self-contained (no hard jsonschema
dependency); `schemas/evidence-contract.schema.json` is the canonical spec for external validators.
"""
import hashlib
import json
import os

SCHEMA_VERSION = "0.2"
EVIDENCE_CHANNELS = {f"L{i}" for i in range(11)}
EVIDENCE_KINDS = {
    "regression_tests", "candidate_blind_test", "property_test", "metamorphic_test", "mutation_test",
    "differential_behavior", "affected_test_slice", "protected_path_gate", "diff_integrity_check",
    "compile", "type_check", "static_analysis", "security_scan", "performance_gate",
    "architecture_invariant", "human_approval",
}
_OBLIGATION_FIELDS = ("obligation_id", "requirement", "source", "preconditions", "expected_effect",
                      "acceptable_evidence", "rejection_condition", "unknown_condition")
_CONTRACT_FIELDS = ("task_id", "objective", "repository", "base_commit", "requirements", "assumptions",
                    "protected_paths", "permitted_paths", "mandatory_obligations", "optional_obligations",
                    "required_evidence_channels", "test_isolation_policy", "resource_budget",
                    "termination_policy", "human_approval_policy", "schema_version", "contract_hash")


class ContractError(ValueError):
    pass


def make_obligation(obligation_id, requirement, source, expected_effect, acceptable_evidence,
                    rejection_condition, unknown_condition, preconditions=None):
    if not acceptable_evidence:
        raise ContractError(f"{obligation_id}: acceptable_evidence must be non-empty")
    bad = set(acceptable_evidence) - EVIDENCE_KINDS
    if bad:
        raise ContractError(f"{obligation_id}: unknown evidence kinds {bad}")
    return {
        "obligation_id": obligation_id, "requirement": requirement, "source": source,
        "preconditions": list(preconditions or []), "expected_effect": expected_effect,
        "acceptable_evidence": list(acceptable_evidence),
        "rejection_condition": rejection_condition, "unknown_condition": unknown_condition,
    }


def _validate_obligation(o, where):
    if not isinstance(o, dict):
        raise ContractError(f"{where}: obligation must be an object")
    missing = [f for f in _OBLIGATION_FIELDS if f not in o]
    if missing:
        raise ContractError(f"{where}: obligation missing {missing}")
    if not o["obligation_id"] or not o["requirement"]:
        raise ContractError(f"{where}: obligation_id/requirement must be non-empty")
    if not o["acceptable_evidence"]:
        raise ContractError(f"{where} {o['obligation_id']}: acceptable_evidence empty")
    bad = set(o["acceptable_evidence"]) - EVIDENCE_KINDS
    if bad:
        raise ContractError(f"{where} {o['obligation_id']}: unknown evidence {bad}")


def validate(contract):
    """Structural validation (no external deps). Raises ContractError on any violation."""
    missing = [f for f in _CONTRACT_FIELDS if f not in contract]
    if missing:
        raise ContractError(f"contract missing {missing}")
    if not contract["task_id"] or not contract["objective"]:
        raise ContractError("task_id/objective must be non-empty")
    if not contract["mandatory_obligations"]:
        raise ContractError("at least one mandatory obligation required")
    chans = set(contract["required_evidence_channels"])
    if not chans or (chans - EVIDENCE_CHANNELS):
        raise ContractError(f"bad required_evidence_channels {chans}")
    ids = []
    for grp in ("mandatory_obligations", "optional_obligations"):
        for o in contract[grp]:
            _validate_obligation(o, grp)
            ids.append(o["obligation_id"])
    if len(ids) != len(set(ids)):
        raise ContractError(f"duplicate obligation_id in {ids}")
    return True


def _canonical(contract):
    return json.dumps({k: v for k, v in contract.items() if k != "contract_hash"},
                      sort_keys=True, default=str)


def compute_hash(contract):
    return hashlib.sha256(_canonical(contract).encode()).hexdigest()


def freeze(contract):
    """Validate, stamp the content hash, return the FROZEN contract. Call before candidate generation."""
    contract = {**contract, "contract_hash": ""}
    validate(contract)
    contract["contract_hash"] = compute_hash(contract)
    return contract


def verify_unmutated(contract):
    """True iff the contract's content still matches its stamped hash (no candidate tampered with it)."""
    stamped = contract.get("contract_hash")
    return bool(stamped) and stamped == compute_hash(contract)


def build_contract(task_id, objective, mandatory_obligations, *, repository="", base_commit="",
                   requirements=None, assumptions=None, protected_paths=None, permitted_paths=None,
                   optional_obligations=None, required_evidence_channels=None,
                   test_isolation_policy="candidate-blind; tests frozen+hashed before candidate",
                   resource_budget=None, termination_policy=None,
                   human_approval_policy="protected paths + canonical merge require founder approval"):
    """Assemble, validate, and FREEZE an Evidence Contract. Protected paths always include the test/eval/
    scorer surfaces so a candidate can never satisfy obligations by editing them (reward-hacking defense)."""
    protected = sorted(set((protected_paths or []) + [
        "tests/", "test/", "conftest.py", "swebench/", "run-tests.mjs", "logos/harness.py",
        "logos/evidence_oracle.py", "*.gold", "test_patch"]))
    contract = {
        "task_id": task_id, "objective": objective, "repository": repository, "base_commit": base_commit,
        "requirements": list(requirements or []), "assumptions": list(assumptions or []),
        "protected_paths": protected, "permitted_paths": list(permitted_paths or []),
        "mandatory_obligations": list(mandatory_obligations),
        "optional_obligations": list(optional_obligations or []),
        "required_evidence_channels": list(required_evidence_channels or ["L0", "L1", "L2", "L3"]),
        "test_isolation_policy": test_isolation_policy,
        "resource_budget": resource_budget or {"turns": 4, "wall_seconds": 1800, "usd": None},
        "termination_policy": termination_policy or {
            "accept": "all mandatory obligations ACCEPTABLE AND no protected invariant failed",
            "reject": "any hard evidence channel REJECTED",
            "insufficient": "a required channel could not produce evidence"},
        "human_approval_policy": human_approval_policy,
        "schema_version": SCHEMA_VERSION, "contract_hash": "",
    }
    return freeze(contract)


def _selftest():
    o1 = make_obligation("O1", "Existing text-payload behavior unchanged", "tests",
                         "no regression on text bodies", ["regression_tests", "differential_behavior"],
                         "any previously-passing non-graded test fails", "no related tests exist")
    o2 = make_obligation("O2", "Binary payloads pass through unconverted", "issue",
                         "bytes body stays bytes", ["candidate_blind_test", "property_test"],
                         "body is coerced to str", "cannot construct a binary case")
    c = build_contract("task_demo", "Correct binary request-body handling", [o1, o2],
                       repository="psf/requests", base_commit="abc123")
    assert validate(c) and verify_unmutated(c), "fresh contract must validate + verify"
    assert c["contract_hash"], "must be hashed"
    # protected paths auto-include the test/scorer surfaces (reward-hacking defense)
    assert any(p.startswith("tests") for p in c["protected_paths"]) and "swebench/" in c["protected_paths"]
    # tamper detection: mutate an obligation -> hash no longer matches
    c["mandatory_obligations"][0]["requirement"] = "weakened"
    assert not verify_unmutated(c), "tamper must be detected"
    # validation catches a missing field
    try:
        bad = {k: v for k, v in build_contract("t", "o", [o1]).items() if k != "objective"}
        validate(bad); raise AssertionError("should have raised on missing objective")
    except ContractError:
        pass
    # empty acceptable_evidence rejected at construction
    try:
        make_obligation("Ox", "r", "issue", "e", [], "rej", "unk"); raise AssertionError("empty evidence")
    except ContractError:
        pass
    print("evidence_contract selftest PASS — build/validate/freeze/hash + tamper-detect + reward-hack protected paths")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: evidence_contract.py --selftest")
