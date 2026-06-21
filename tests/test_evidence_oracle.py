"""unittest for the multi-channel Evidence Oracle (v0.2 WP-D)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import evidence_oracle as EO, evidence_contract as EC

def _contract():
    o1 = EC.make_obligation("O1", "no regression", "tests", "e", ["regression_tests"], "r", "u")
    o2 = EC.make_obligation("O2", "binary ok", "issue", "e", ["candidate_blind_test"], "r", "u")
    return EC.build_contract("t", "o", [o1, o2], required_evidence_channels=["L0","L1","L2","L3"])

def _r(s): return lambda c, cand: {"status": s, "detail": "x"}
SRC = "diff --git a/src/m.py b/src/m.py\n+++ b/src/m.py\n+x=1\n"
ALL = {"L1": _r("PASS"), "L2": _r("PASS"), "L3": _r("PASS")}


class TestOracle(unittest.TestCase):
    def test_all_pass_acceptable(self):
        self.assertEqual(EO.evaluate(_contract(), {"diff": SRC}, ALL)["verdict"], EO.ACCEPTABLE)

    def test_integrity_fail_rejected_unappealable(self):
        bad = "diff --git a/tests/t.py b/tests/t.py\n+++ b/tests/t.py\n+x\n"
        self.assertEqual(EO.evaluate(_contract(), {"diff": bad}, ALL)["verdict"], EO.REJECTED)

    def test_missing_runner_insufficient(self):
        v = EO.evaluate(_contract(), {"diff": SRC}, {"L1": _r("PASS"), "L2": _r("PASS")})
        self.assertEqual(v["verdict"], EO.INSUFFICIENT_EVIDENCE)

    def test_hard_regression_fail_rejected(self):
        v = EO.evaluate(_contract(), {"diff": SRC}, {"L1": _r("PASS"), "L2": _r("FAIL"), "L3": _r("PASS")})
        self.assertEqual(v["verdict"], EO.REJECTED)

    def test_runner_crash_is_not_success(self):
        def boom(c, cand): raise RuntimeError("x")
        v = EO.evaluate(_contract(), {"diff": SRC}, {"L1": _r("PASS"), "L2": _r("PASS"), "L3": boom})
        self.assertEqual(v["verdict"], EO.INSUFFICIENT_EVIDENCE)

    def test_tiebreak_cannot_resurrect(self):
        evals = [{"verdict": EO.REJECTED}, {"verdict": EO.ACCEPTABLE}]
        self.assertEqual(EO.tiebreak_among(evals, lambda xs: 0), 1)


if __name__ == "__main__":
    unittest.main()
