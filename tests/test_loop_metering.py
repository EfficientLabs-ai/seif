"""unittest for A4 production metering wired through seif_run + project_harness._receipt.

Pins the per-task metering fields the receipt must carry AND hash-cover:
  attempt_number, empty_response_retries, checkpoint_id, evidence_result, final_outcome
(plus route_id_selected, threaded from A3). Coverage:
  - present + correctly typed on every receipt (accepted, rejected, no_change, budget-exhausted);
  - hash-covered (recomputing the chain hash over the metering-bearing record reproduces rec['h']);
  - _claude_edit surfaces empty_retries on the usage dict, and the loop sums it across steps;
  - checkpoint_id is the registered healthy checkpoint id on accept, None on reject;
  - final_outcome takes the right value per disposition.
All hermetic: ledgers pinned to temp, _claude_edit injected (no real claude), no remote (no PR).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import seif_run as SR  # noqa: E402
import project_harness as H  # noqa: E402
import checkpoint as CP  # noqa: E402


def _hash_of(rec):
    """Recompute a receipt's chain hash the way _receipt does (prev + sorted-json of all but 'h')."""
    return hashlib.sha256(
        (rec["prev"] + json.dumps({k: v for k, v in rec.items() if k != "h"}, sort_keys=True)).encode()
    ).hexdigest()[:16]


_METERING_KEYS = ("attempt_number", "empty_response_retries", "checkpoint_id",
                  "evidence_result", "final_outcome", "route_id_selected")


class ReceiptMeteringUnitTest(unittest.TestCase):
    """_receipt(metering=...) merges + hash-covers the fields; without it the old shape is preserved."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-meter-")
        self._orig = H.RECEIPTS
        H.RECEIPTS = os.path.join(self.tmp, "r.jsonl")

    def tearDown(self):
        H.RECEIPTS = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_metering_fields_present_typed_and_hash_covered(self):
        metering = {"attempt_number": 2, "empty_response_retries": 1, "checkpoint_id": "abc123",
                    "evidence_result": "tests pass; integrity clean", "final_outcome": "ACCEPTED_PR",
                    "route_id_selected": "seif-source-fix"}
        rec = H._receipt("/repo", "task", "pytest", {"exit_code": 0, "outcome": "pass"}, "diff",
                         usage={"input_tokens": 5, "cost_usd": 0.0, "calls": 1}, metering=metering)
        for k, v in metering.items():
            self.assertEqual(rec[k], v)
        self.assertIsInstance(rec["attempt_number"], int)
        self.assertIsInstance(rec["empty_response_retries"], int)
        self.assertEqual(rec["h"], _hash_of(rec))            # metering is inside the integrity hash

    def test_checkpoint_id_may_be_null_and_still_hash_covered(self):
        metering = {"attempt_number": 1, "empty_response_retries": 0, "checkpoint_id": None,
                    "evidence_result": "tests fail (exit 1)", "final_outcome": "REJECTED",
                    "route_id_selected": "none"}
        rec = H._receipt("/repo", "t", "pytest", {"exit_code": 1, "outcome": "fail"}, "diff", metering=metering)
        self.assertIsNone(rec["checkpoint_id"])              # null is a legitimate, recorded value
        self.assertEqual(rec["h"], _hash_of(rec))

    def test_no_metering_keeps_old_shape(self):
        rec = H._receipt("/repo", "t", "pytest", {"exit_code": 0, "outcome": "pass"}, "diff")
        for k in _METERING_KEYS:
            self.assertNotIn(k, rec)                          # absent → old receipts/callers unaffected
        self.assertEqual(rec["h"], _hash_of(rec))


class ClaudeEditEmptyRetriesTest(unittest.TestCase):
    """_claude_edit tags the usage dict with empty_retries without changing the (rc, usage) 2-tuple."""

    _ENVELOPE = json.dumps({"model": "m", "total_cost_usd": 0.0,
                            "usage": {"input_tokens": 7, "output_tokens": 1}})

    def test_empty_retries_zero_on_first_call_success(self):
        fake = mock.Mock(returncode=0, stdout=self._ENVELOPE, stderr="")
        with mock.patch.object(SR.subprocess, "run", return_value=fake):
            rc, usage = SR._claude_edit("/tmp", "t", "", True, 5)
        self.assertEqual(usage["empty_retries"], 0)

    def test_empty_retries_counts_retries_before_a_real_call(self):
        empty = mock.Mock(returncode=0, stdout='{"usage":{"input_tokens":0}}', stderr="")
        real = mock.Mock(returncode=0, stdout=self._ENVELOPE, stderr="")
        with mock.patch.object(SR.subprocess, "run", side_effect=[empty, empty, real]):
            rc, usage = SR._claude_edit("/tmp", "t", "", True, 5)
        self.assertEqual(usage["input_tokens"], 7)            # the real call's usage is returned
        self.assertEqual(usage["empty_retries"], 2)           # two empties were retried past

    def test_empty_retries_on_all_empty_is_attempts_minus_one(self):
        empty = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(SR.subprocess, "run", return_value=empty) as run:
            rc, usage = SR._claude_edit("/tmp", "t", "", True, 5)
        self.assertEqual(run.call_count, 3)                   # bounded
        self.assertEqual(usage["empty_retries"], 2)           # 3 attempts → 2 retries

    def test_empty_retries_on_timeout_is_zero(self):
        with mock.patch.object(SR.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)):
            rc, usage = SR._claude_edit("/tmp", "t", "", True, 5)
        self.assertEqual(usage["empty_retries"], 0)


class LoopMeteringIntegrationTest(unittest.TestCase):
    """End-to-end through seif_run: the receipt carries the right metering for each disposition."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-meterloop-")
        self._h, self._l, self._f = H.RECEIPTS, CP.LEDGER, CP.FAILURES
        H.RECEIPTS = os.path.join(self.tmp, "r.jsonl")
        CP.LEDGER = os.path.join(self.tmp, "c.jsonl")
        CP.FAILURES = os.path.join(self.tmp, "f.jsonl")
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "calc.py"), "w").write("def add(a, b):\n    return a - b\n")  # bug
        open(os.path.join(self.repo, "test_calc.py"), "w").write(
            "import unittest\nfrom calc import add\n"
            "class T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(add(2, 3), 5)\n")
        g = lambda *a: subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True)
        g("add", "-A"); g("commit", "-qm", "base")
        self.cmd = f"{sys.executable} -m unittest -q test_calc"

    def tearDown(self):
        H.RECEIPTS, CP.LEDGER, CP.FAILURES = self._h, self._l, self._f
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _all_keys_present(self, rec):
        for k in _METERING_KEYS:
            self.assertIn(k, rec, f"metering field {k} missing from receipt")
        self.assertEqual(rec["h"], _hash_of(rec))

    def test_accepted_run_records_attempt_checkpoint_and_outcome(self):
        def honest(wt, *a, **k):
            open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
            u = SR.UM.empty(); u["input_tokens"] = 10; u["empty_retries"] = 3; return 0, u
        with mock.patch.object(SR, "_claude_edit", side_effect=honest):
            r = SR.seif_run(self.repo, "fix add", self.cmd, budget=2, make_pr=False, route=False)
        rec = r["receipt"]
        self.assertTrue(r["accepted"])
        self._all_keys_present(rec)
        self.assertEqual(rec["final_outcome"], "ACCEPTED_PR")
        self.assertEqual(rec["attempt_number"], 1)                    # accepted on the first step
        self.assertEqual(rec["empty_response_retries"], 3)           # summed from the editor's usage
        self.assertEqual(rec["checkpoint_id"], r["checkpoint"]["id"])  # the minted healthy checkpoint
        self.assertIsNotNone(rec["checkpoint_id"])

    def test_rejected_run_has_null_checkpoint_and_reject_outcome(self):
        # tests stay red but agent keeps changing source → REJECTED with budget remaining; no checkpoint.
        calls = {"n": 0}

        def wrong(wt, *a, **k):
            calls["n"] += 1
            open(os.path.join(wt, "calc.py"), "w").write(f"def add(a, b):\n    return a * {calls['n']}\n")
            return 0, SR.UM.empty()
        with mock.patch.object(SR, "_claude_edit", side_effect=wrong):
            r = SR.seif_run(self.repo, "fix add", self.cmd, budget=3, make_pr=False, route=False)
        rec = r["receipt"]
        self.assertFalse(r["accepted"])
        self._all_keys_present(rec)
        self.assertEqual(rec["final_outcome"], "BUDGET_EXHAUSTED")    # red through the whole budget
        self.assertIsNone(rec["checkpoint_id"])
        self.assertEqual(rec["attempt_number"], 3)                    # ran all budget steps

    def test_empty_response_retries_summed_across_budget_steps(self):
        # the loop must SUM each step's empty_retries (the editor reports per-call); over 2 failing steps
        # that each absorbed retries, the receipt's empty_response_retries is the total.
        steps = {"n": 0}

        def wrong_with_retries(wt, *a, **k):
            steps["n"] += 1
            open(os.path.join(wt, "calc.py"), "w").write(f"def add(a, b):\n    return a * {steps['n']}\n")
            u = SR.UM.empty(); u["input_tokens"] = 5; u["empty_retries"] = 2; return 0, u  # 2 per step
        with mock.patch.object(SR, "_claude_edit", side_effect=wrong_with_retries):
            r = SR.seif_run(self.repo, "fix add", self.cmd, budget=2, make_pr=False, route=False)
        rec = r["receipt"]
        self.assertFalse(r["accepted"])
        self.assertEqual(rec["attempt_number"], 2)
        self.assertEqual(rec["empty_response_retries"], 4)           # 2 steps × 2 retries each, summed
        # and the summed retries are NOT leaked into the spend/usage block (that sums only token classes)
        self.assertNotIn("empty_retries", rec.get("usage", {}))

    def test_no_change_run_records_no_change_outcome(self):
        with mock.patch.object(SR, "_claude_edit", side_effect=lambda *a, **k: (0, SR.UM.empty())):
            r = SR.seif_run(self.repo, "fix add", self.cmd, budget=2, make_pr=False, route=False)
        rec = r["receipt"]
        self.assertFalse(r["accepted"])
        self._all_keys_present(rec)
        self.assertEqual(rec["final_outcome"], "REJECTED")           # no_change (budget not exhausted-by-fail)
        self.assertEqual(rec["attempt_number"], 1)
        self.assertIn("no patch", rec["evidence_result"])

    def test_unexpected_error_mints_error_receipt_then_reraises(self):
        # an unexpected fault inside the run (here: the editor raises) must mint an ERROR receipt — recorded,
        # metering-bearing, hash-covered — BEFORE the original exception propagates (no silent gap).
        def boom(wt, *a, **k):
            raise RuntimeError("editor exploded")
        with mock.patch.object(SR, "_claude_edit", side_effect=boom):
            with self.assertRaises(RuntimeError):
                SR.seif_run(self.repo, "fix add", self.cmd, budget=2, make_pr=False, route=False)
        # the ERROR receipt is the last line of the (temp) ledger
        with open(H.RECEIPTS) as f:
            rec = json.loads([ln for ln in f if ln.strip()][-1])
        self.assertEqual(rec["final_outcome"], "ERROR")
        self.assertIsNone(rec["checkpoint_id"])
        self.assertIn("RuntimeError", rec["evidence_result"])
        self._all_keys_present(rec)                          # all metering fields present + hash-covered

    def test_integrity_violation_records_reject_and_evidence(self):
        def cheat(wt, *a, **k):
            # pass tests by gutting the test (reward hack) → integrity gate rejects it
            open(os.path.join(wt, "test_calc.py"), "w").write(
                "import unittest\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertTrue(True)\n")
            return 0, SR.UM.empty()
        with mock.patch.object(SR, "_claude_edit", side_effect=cheat):
            r = SR.seif_run(self.repo, "fix add", self.cmd, budget=1, make_pr=False, route=False)
        rec = r["receipt"]
        self.assertFalse(r["accepted"])
        self._all_keys_present(rec)
        self.assertEqual(rec["final_outcome"], "REJECTED")
        self.assertIsNone(rec["checkpoint_id"])
        self.assertIn("integrity FAIL", rec["evidence_result"])


if __name__ == "__main__":
    unittest.main()
