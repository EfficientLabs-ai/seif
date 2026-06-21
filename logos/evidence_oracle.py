#!/usr/bin/env python3
"""SEIF Multi-Channel Evidence Oracle (v0.2 WP-D) — the keystone. Combines the evidence channels into a
TRI-STATE verdict, integrating WP-A (Evidence Contract), WP-E (Integrity Guard, L0), and WP-C (Mutation,
L5), plus injectable execution channels (compile L1, regression L2, candidate-blind tests L3, …).

Binding invariants (from the v0.2 directive):
  • Verdict ∈ {ACCEPTABLE, REJECTED, INSUFFICIENT_EVIDENCE}. **Unknown is NEVER folded into success.**
  • A HARD channel FAIL ⇒ REJECTED, and an LLM may NEVER override it (the oracle calls no LLM at all).
  • ACCEPTABLE requires: no hard fail, every REQUIRED channel PASS, and every MANDATORY obligation covered
    by ≥1 passing acceptable-evidence channel. Anything else ⇒ INSUFFICIENT_EVIDENCE.
An LLM verifier may, OUTSIDE this function, explain failures or tie-break AMONG already-ACCEPTABLE
candidates — never change a verdict (see `tiebreak_among`).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import integrity_guard as IG   # noqa: E402

PASS, FAIL, INSUFFICIENT, SKIP = "PASS", "FAIL", "INSUFFICIENT", "SKIP"
ACCEPTABLE, REJECTED, INSUFFICIENT_EVIDENCE = "ACCEPTABLE", "REJECTED", "INSUFFICIENT_EVIDENCE"

# evidence kind (contract) -> channel level
EVIDENCE_CHANNEL = {
    "diff_integrity_check": "L0", "protected_path_gate": "L0",
    "compile": "L1", "type_check": "L1",
    "regression_tests": "L2", "affected_test_slice": "L2",
    "candidate_blind_test": "L3",
    "property_test": "L4", "metamorphic_test": "L4",
    "mutation_test": "L5",
    "differential_behavior": "L6",
    "static_analysis": "L7", "security_scan": "L7",
    "performance_gate": "L8",
    "architecture_invariant": "L9",
    "human_approval": "L10",
}
# structural gates whose FAIL is unappealable
HARD_CHANNELS = {"L0", "L1", "L2", "L9", "L10"}


def _l0_integrity(contract, candidate):
    clean, rep = IG.is_clean(candidate.get("diff", ""), contract.get("protected_paths", []),
                             candidate.get("graded_ids", []))
    return {"status": PASS if clean else FAIL, "detail": {"hard": rep["hard"][:5], "flags": rep["flags"][:5]}}


def evaluate(contract, candidate, channel_runners=None):
    """contract: frozen Evidence Contract. candidate: {diff, graded_ids, ...}. channel_runners: {chan_id ->
    fn(contract,candidate)->{status,detail}} for L1+ (L0 is built-in). Returns the tri-state verdict + the
    full per-channel + per-obligation breakdown."""
    runners = channel_runners or {}
    results = {"L0": {"channel": "L0", "hard": True, **_l0_integrity(contract, candidate)}}

    needed = set(contract.get("required_evidence_channels", []))
    for o in contract.get("mandatory_obligations", []) + contract.get("optional_obligations", []):
        for ev in o["acceptable_evidence"]:
            if ev in EVIDENCE_CHANNEL:
                needed.add(EVIDENCE_CHANNEL[ev])
    for ch in sorted(needed):
        if ch == "L0":
            continue
        runner = runners.get(ch)
        if runner is None:
            results[ch] = {"channel": ch, "hard": ch in HARD_CHANNELS, "status": INSUFFICIENT,
                           "detail": "no runner wired"}
            continue
        try:
            r = runner(contract, candidate) or {}
            status = r.get("status", INSUFFICIENT)
            if status not in (PASS, FAIL, INSUFFICIENT, SKIP):
                status = INSUFFICIENT
        except Exception as e:  # noqa: BLE001 - a runner crash is NOT evidence of success
            r, status = {"detail": repr(e)}, INSUFFICIENT
        results[ch] = {"channel": ch, "hard": ch in HARD_CHANNELS, "status": status, "detail": r.get("detail")}

    # mandatory obligation coverage: ≥1 acceptable-evidence channel for the obligation must PASS
    coverage = []
    for o in contract.get("mandatory_obligations", []):
        chans = sorted({EVIDENCE_CHANNEL[ev] for ev in o["acceptable_evidence"] if ev in EVIDENCE_CHANNEL})
        covered = any(results.get(c, {}).get("status") == PASS for c in chans)
        coverage.append({"obligation_id": o["obligation_id"], "covered": covered, "channels": chans})

    hard_fail = [r["channel"] for r in results.values() if r["status"] == FAIL and r["hard"]]
    required = list(contract.get("required_evidence_channels", []))
    # defend-in-depth: a degenerate contract (no obligations / no required channels) makes the all()
    # checks vacuously true -> it must NEVER be ACCEPTABLE (there is nothing actually proven).
    degenerate = (not contract.get("mandatory_obligations")) or (not required)
    required_ok = all(results.get(c, {}).get("status") == PASS for c in required)
    coverage_ok = all(c["covered"] for c in coverage)

    if hard_fail:
        verdict = REJECTED
    elif degenerate:
        verdict = INSUFFICIENT_EVIDENCE     # nothing to prove / no required evidence -> not ACCEPTABLE
    elif required_ok and coverage_ok:
        verdict = ACCEPTABLE
    else:
        verdict = INSUFFICIENT_EVIDENCE     # default-safe: never ACCEPTABLE on any gap/unknown

    reasons = []
    if hard_fail:
        reasons.append(f"hard gate FAILED: {hard_fail} (unappealable)")
    if degenerate:
        reasons.append("degenerate contract: no mandatory obligations and/or no required evidence channels")
    if not required_ok:
        reasons.append("a required evidence channel did not PASS")
    if not coverage_ok:
        reasons.append("a mandatory obligation lacks passing evidence")
    return {"verdict": verdict, "channels": results, "obligation_coverage": coverage,
            "reasons": reasons or ["all required channels passed; all mandatory obligations covered"],
            "policy": "LLM may explain/tie-break among ACCEPTABLE candidates only; never overrides a hard FAIL"}


def tiebreak_among(evaluations, chooser):
    """Select ONE among ALREADY-ACCEPTABLE candidates. `chooser(acceptable)->index` may be an LLM. If any
    candidate is not ACCEPTABLE it is dropped first — the LLM can never resurrect a REJECTED/INSUFFICIENT one."""
    acceptable = [(i, e) for i, e in enumerate(evaluations) if e.get("verdict") == ACCEPTABLE]
    if not acceptable:
        return None
    if len(acceptable) == 1:
        return acceptable[0][0]
    pick = chooser([e for _, e in acceptable])
    return acceptable[pick][0] if isinstance(pick, int) and 0 <= pick < len(acceptable) else acceptable[0][0]


def _selftest():
    import evidence_contract as EC
    o1 = EC.make_obligation("O1", "no regression", "tests", "text bodies unchanged",
                            ["regression_tests"], "a passing test breaks", "no related tests")
    o2 = EC.make_obligation("O2", "binary passes through", "issue", "bytes stay bytes",
                            ["candidate_blind_test"], "coerced to str", "no binary case")
    c = EC.build_contract("t", "fix binary body", [o1, o2], repository="psf/requests",
                          required_evidence_channels=["L0", "L1", "L2", "L3"])
    src = "diff --git a/src/m.py b/src/m.py\n+++ b/src/m.py\n+x=1\n"

    def runner(status):
        return lambda con, cand: {"status": status, "detail": "stub"}
    allpass = {"L1": runner(PASS), "L2": runner(PASS), "L3": runner(PASS)}

    # 1) everything passes -> ACCEPTABLE
    v = evaluate(c, {"diff": src}, allpass)
    assert v["verdict"] == ACCEPTABLE, v

    # 2) integrity L0 FAIL (candidate edits a test file) -> REJECTED, unappealable, even with all runners PASS
    bad = "diff --git a/tests/test_m.py b/tests/test_m.py\n+++ b/tests/test_m.py\n+assert True\n"
    v = evaluate(c, {"diff": bad}, allpass)
    assert v["verdict"] == REJECTED and "L0" in str(v["reasons"]), v

    # 3) a required channel has NO runner -> INSUFFICIENT_EVIDENCE (never ACCEPTABLE on unknown)
    v = evaluate(c, {"diff": src}, {"L1": runner(PASS), "L2": runner(PASS)})  # L3 missing
    assert v["verdict"] == INSUFFICIENT_EVIDENCE, v

    # 4) hard L2 regression FAIL -> REJECTED
    v = evaluate(c, {"diff": src}, {"L1": runner(PASS), "L2": runner(FAIL), "L3": runner(PASS)})
    assert v["verdict"] == REJECTED, v

    # 5) non-hard channel FAIL (L3 acceptance) leaving O2 uncovered -> INSUFFICIENT (not REJECTED)
    v = evaluate(c, {"diff": src}, {"L1": runner(PASS), "L2": runner(PASS), "L3": runner(FAIL)})
    assert v["verdict"] == INSUFFICIENT_EVIDENCE, v

    # 6) tiebreak never resurrects a non-ACCEPTABLE candidate
    evals = [{"verdict": REJECTED}, {"verdict": ACCEPTABLE}, {"verdict": INSUFFICIENT_EVIDENCE}]
    assert tiebreak_among(evals, lambda xs: 0) == 1, "must pick the only ACCEPTABLE"
    assert tiebreak_among([{"verdict": REJECTED}], lambda xs: 0) is None
    print("evidence_oracle selftest PASS — tri-state; hard-gate unappealable; unknown->INSUFFICIENT (never ACCEPTABLE); "
          "obligation coverage; tiebreak can't resurrect rejected candidates")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: evidence_oracle.py --selftest")
