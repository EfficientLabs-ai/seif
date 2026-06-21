#!/usr/bin/env python3
"""SEIF Agent Harness — the EXECUTION ORACLE. Verification by EVIDENCE (real test exit codes),
not LLM opinion. This is Pillar 3 of the SEIF/LOGOS PRD, built honestly.

THE CRITICAL GUARD (without it the whole eval is void): the PRD's "inject the repo's regression
suite" is unsafe on SWE-bench, because the repo's existing tests INCLUDE the graded PASS_TO_PASS
ids — feeding them back leaks the grading oracle. So the harness runs only tests that are PROVABLY
DISJOINT from the instance's graded set (FAIL_TO_PASS ∪ PASS_TO_PASS), asserted in code and logged
to the SEIF ledger per instance. The graded FAIL_TO_PASS don't exist at base_commit anyway (they're
added by the held-out test_patch), so the regression signal here = the repo's OTHER existing tests
near the change — uncorrelated with the worker's LLM and with the grader.

Ground truth = the OS exit code from pytest in the locked sandbox. No LLM interprets the result.
"""
import json
import os
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kernel"))
import arm_b_testbed as TB      # noqa: E402  (instance-image sandbox)
try:
    import seif_kernel as K     # noqa: E402
except Exception:               # noqa: BLE001
    K = None

TEST_FILE_RE = __import__("re").compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py)$")


def _norm(p):
    """Repo-relative POSIX path, no leading './' — so OS-sep and graded-id paths compare apples-to-apples."""
    p = p.replace(os.sep, "/")
    return p[2:] if p.startswith("./") else p


def _loadlist(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except json.JSONDecodeError:
            return [t for t in x.replace(",", " ").split() if t]
    return list(x or [])


def graded_ids(inst):
    """The full graded set for an instance: FAIL_TO_PASS ∪ PASS_TO_PASS (node ids)."""
    return set(_loadlist(inst.get("FAIL_TO_PASS"))) | set(_loadlist(inst.get("PASS_TO_PASS")))


def _node_file(node_id):
    return node_id.split("::", 1)[0]


def discover_regression_tests(repo, graded, max_files=8):
    """Existing test FILES in the repo, EXCLUDING any file that hosts a graded node (file-level
    disjointness, normalized to POSIX repo-relative paths)."""
    graded_files = {_norm(_node_file(n)) for n in graded}
    found = []
    for dp, dns, fns in os.walk(repo):
        dns[:] = [d for d in dns if d != ".git"]
        for fn in fns:
            rel = _norm(os.path.relpath(os.path.join(dp, fn), repo))
            if TEST_FILE_RE.search(rel) and rel not in graded_files:
                found.append(rel)
    found.sort()
    return found[:max_files]


def assert_disjoint(selected, graded):
    """HARD guard: a selected regression target must never be (or host) a graded node. Raises."""
    graded_files = {_norm(_node_file(n)) for n in graded}
    graded_nodes = {_norm(n) for n in graded}
    bad = [s for s in selected
           if _norm(s) in graded_files or _norm(s) in graded_nodes or _norm(_node_file(s)) in graded_files]
    if bad:
        raise RuntimeError(f"ORACLE-LEAK GUARD TRIPPED: regression set intersects graded tests: {bad[:5]}")


def adjudicate(img, repo, test_targets, graded=(), timeout=180):
    """Run the selected tests in the locked sandbox; GROUND TRUTH = exit code. No LLM interprets it.
    PROVABLE no-leak: every graded node id is explicitly `--deselect`ed, so even if a conftest/plugin
    collects one dynamically from a target file, pytest will NOT run it. Returns
    {ran, outcome, exit_code, stdout, stderr}. outcome: pass|fail|timeout|error|no_tests."""
    if not test_targets:
        return {"ran": False, "outcome": "no_tests", "exit_code": None, "stdout": "", "stderr": ""}
    deselect = " ".join(f"--deselect {shlex.quote(g)}" for g in graded)
    cmd = ("python -m pytest -q -p no:cacheprovider --no-header " + deselect + " "
           + " ".join(shlex.quote(t) for t in test_targets)).strip()
    r = TB.run_in_testbed(img, repo, cmd, timeout=timeout)
    return {"ran": True, **r}


def verify(inst, img, repo, prompt, patch, task_id=None, max_files=8, timeout=180):
    """Full evidence verification for one candidate: pick disjoint regression tests, prove
    disjointness, execute, and emit a signed SEIF receipt. The exit code decides — not an LLM."""
    graded = graded_ids(inst)
    targets = discover_regression_tests(repo, graded, max_files=max_files)
    assert_disjoint(targets, graded)                      # build-break on any overlap
    result = adjudicate(img, repo, targets, graded=graded, timeout=timeout)
    outcome = result.get("outcome")
    # Three distinct states — NEVER conflate "no signal" with "verified", and never treat a graded
    # test as the signal (it's deselected + file-excluded). regressed = hard reject.
    if outcome == "no_tests":
        verdict = "NO_REGRESSION_SIGNAL"   # no disjoint tests exist near the change — weak, not proof
    elif outcome == "pass":
        verdict = "REGRESSION_CLEAN"       # disjoint tests ran and held (exit 0) — real evidence
    else:
        verdict = "REGRESSED"              # a previously-passing non-graded test broke — hard reject
    rec = {
        "instance_id": inst["instance_id"],
        "prompt_sha": (K._sha(prompt)[:16] if K else None),
        "patch_sha": (K._sha(patch)[:16] if K else None),
        "regression_targets": targets,
        "regression_disjoint_from_graded": True,
        "graded_count": len(graded),
        "exit_code": result.get("exit_code"),
        "outcome": outcome,
        "verdict": verdict,
        "stdout_tail": (result.get("stdout") or "")[-1200:],
        "evidence": "os-exit-code; graded ids file-excluded AND --deselected; no LLM interpretation",
    }
    if K and task_id:
        try:
            K.append_event("seif-harness", "verify.evidence",
                           {"verdict": verdict, "exit_code": rec["exit_code"],
                            "regression_files": len(targets), "disjoint": True}, task_id=task_id)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[harness] ledger: {e!r}\n")
    rec["regressed"] = (verdict == "REGRESSED")          # hard reject signal for the arm/ATMS
    rec["clean_evidence"] = (verdict == "REGRESSION_CLEAN")  # the only POSITIVE evidence state
    return rec


# ---------------- self-test (no docker / no model needed) ----------------
def _selftest():
    import tempfile
    repo = tempfile.mkdtemp(prefix="harness-")
    os.makedirs(os.path.join(repo, "pkg", "tests"))
    for p in ["tests/test_core.py", "tests/test_utils.py", "pkg/tests/test_pkg.py", "pkg/module.py"]:
        os.makedirs(os.path.join(repo, os.path.dirname(p)), exist_ok=True)
        open(os.path.join(repo, p), "w").write("def test_x():\n    assert True\n")
    inst = {"instance_id": "demo-1",
            "FAIL_TO_PASS": json.dumps(["tests/test_core.py::test_added"]),   # added by held-out test_patch
            "PASS_TO_PASS": json.dumps(["tests/test_utils.py::test_x"])}       # EXISTING graded test
    graded = graded_ids(inst)
    targets = discover_regression_tests(repo, graded)
    assert "tests/test_utils.py" not in targets, f"LEAK: graded PASS_TO_PASS file selected! {targets}"
    assert "tests/test_core.py" not in targets, f"graded FAIL_TO_PASS file selected! {targets}"
    assert "pkg/tests/test_pkg.py" in targets, f"missed a safe regression file: {targets}"
    assert_disjoint(targets, graded)                                          # must NOT raise
    try:
        assert_disjoint(["tests/test_utils.py"], graded)                      # must raise
        raise AssertionError("guard failed to trip on a graded file")
    except RuntimeError:
        pass
    print(f"harness selftest PASS — disjoint guard works (selected {targets}, graded files excluded)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: harness.py --selftest   (verify() is driven by the harness arm)")
