"""unittest for the round-2 frontier/escalation bench (logos/round2_bench.py) — escalation logic mocked.

Pins the escalation router: it tries cheapest first, STOPS at the first model that resolves, accumulates
cost across attempts, records the resolver, and reports unresolved (with summed cost) only if every rung
fails. Plus the fixture builds and all graded tasks fail before fix.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import round2_bench as R  # noqa: E402


def _result(resolved, cost):
    return {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "cost_usd": cost, "model": None, "resolved": resolved}


class EscalationTest(unittest.TestCase):
    def test_stops_at_first_resolver_and_sums_cost(self):
        # haiku fails, sonnet resolves → stop before opus; cost = haiku + sonnet
        seq = iter([_result(False, 0.10), _result(True, 0.25)])
        with mock.patch.object(R, "one_call", side_effect=lambda *a, **k: next(seq)):
            e = R.escalate("/repo", R.TASKS[0])
        self.assertTrue(e["resolved"])
        self.assertEqual(e["resolver"], R.SONNET)
        self.assertAlmostEqual(e["cost_usd"], 0.35)
        self.assertEqual(len(e["attempts"]), 2)        # opus never tried

    def test_resolves_at_cheapest_when_haiku_succeeds(self):
        with mock.patch.object(R, "one_call", side_effect=lambda *a, **k: _result(True, 0.09)):
            e = R.escalate("/repo", R.TASKS[0])
        self.assertEqual(e["resolver"], R.HAIKU)
        self.assertEqual(len(e["attempts"]), 1)
        self.assertAlmostEqual(e["cost_usd"], 0.09)

    def test_unresolved_after_full_ladder_sums_all_cost(self):
        seq = iter([_result(False, 0.10), _result(False, 0.25), _result(False, 0.65)])
        with mock.patch.object(R, "one_call", side_effect=lambda *a, **k: next(seq)):
            e = R.escalate("/repo", R.TASKS[0])
        self.assertFalse(e["resolved"])
        self.assertIsNone(e["resolver"])
        self.assertEqual(len(e["attempts"]), 3)        # tried the whole ladder
        self.assertAlmostEqual(e["cost_usd"], 1.00)

    def test_ladder_order_is_cheap_to_strong(self):
        self.assertEqual(R.LADDER, [R.HAIKU, R.SONNET, R.OPUS])


class FixtureTest(unittest.TestCase):
    def test_all_graded_tasks_fail_before_fix(self):
        repo = R.build_fixture(tempfile.mkdtemp(prefix="t-r2-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(repo, ignore_errors=True))
        for t in R.TASKS:
            p = subprocess.run([sys.executable, "-m", "unittest", t["mod"]], cwd=repo, capture_output=True)
            self.assertNotEqual(p.returncode, 0, f"{t['id']} must fail before fix")


if __name__ == "__main__":
    unittest.main()
