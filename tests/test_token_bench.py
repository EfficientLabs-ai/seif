"""unittest for token_bench — the fast token-economics A/B harness.

Uses mocked claude (no real model calls), so these are fast and free. They pin: the fixture builds a
real git repo whose tests FAIL before any fix; the arms record usage; and totals aggregate tokens/cost +
the cost-per-resolved denominator correctly across resolved and unresolved tasks.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import token_bench as TB  # noqa: E402
import seif_run as SR     # noqa: E402
import project_harness as H  # noqa: E402


class FixtureTest(unittest.TestCase):
    def test_fixture_is_a_git_repo_with_failing_tests(self):
        repo = TB.build_fixture(tempfile.mkdtemp(prefix="t-fix-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(repo, ignore_errors=True))
        self.assertTrue(os.path.isdir(os.path.join(repo, ".git")))
        self.assertTrue(os.path.exists(os.path.join(repo, "pkg", "ops.py")))
        # the planted bug makes the matching test FAIL before any fix (non-zero exit)
        mod = TB._TASKS[0][2]
        p = subprocess.run([sys.executable, "-m", "unittest", mod], cwd=repo, capture_output=True)
        self.assertNotEqual(p.returncode, 0, "fixture test must fail before the fix is applied")


class TotalsTest(unittest.TestCase):
    def test_totals_sum_tokens_calls_and_cost_per_resolved(self):
        rows = [
            {"resolved": True, "usage": {"input_tokens": 100, "output_tokens": 10, "cost_usd": 0.10, "calls": 2}},
            {"resolved": False, "usage": {"input_tokens": 50, "output_tokens": 5, "cost_usd": 0.05, "calls": 3}},
        ]
        t = TB._totals(rows)
        self.assertEqual(t["input_tokens"], 150)
        self.assertEqual(t["calls"], 5)                 # 2 + 3, real model-call count (not task count)
        self.assertEqual(t["tasks"], 2)
        self.assertEqual(t["resolved"], 1)
        self.assertAlmostEqual(t["cost_usd"], 0.15)
        # honest denominator: cost is divided by RESOLVED tasks only (wasted spend still counts)
        self.assertAlmostEqual(t["cost_per_resolved"], 0.15)

    def test_oneshot_usage_without_calls_counts_as_one(self):
        rows = [{"resolved": True, "usage": {"input_tokens": 7, "cost_usd": 0.01}}]   # no 'calls' key
        self.assertEqual(TB._totals(rows)["calls"], 1)

    def test_zero_resolved_denominator_is_none_not_crash(self):
        rows = [{"resolved": False, "usage": {"input_tokens": 1, "cost_usd": 0.0, "calls": 1}}]
        self.assertIsNone(TB._totals(rows)["cost_per_resolved"])


class ArmTest(unittest.TestCase):
    def test_run_oneshot_records_usage_and_resolution(self):
        repo = TB.build_fixture(tempfile.mkdtemp(prefix="t-arm-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(repo, ignore_errors=True))
        usage = {"input_tokens": 42, "output_tokens": 3, "cost_usd": 0.02, "model": "m"}
        # mock the model edit (return rc + usage) and the test run (claim pass) — no real claude
        with mock.patch.object(SR, "_claude_edit", return_value=(0, usage)), \
             mock.patch.object(H, "run_tests", return_value={"outcome": "pass", "exit_code": 0}):
            out = TB.run_oneshot(repo, "fix it", "true", timeout=5)
        self.assertTrue(out["resolved"])
        self.assertEqual(out["usage"]["input_tokens"], 42)
        self.assertEqual(out["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
