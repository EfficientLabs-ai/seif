"""unittest for the E3 model-routing bench (logos/e3_bench.py) — pure summarize logic, no real claude.

Pins the honest metric: cost-per-RESOLVED (not per-call), resolve-rate, per-model filtering, and that
empty/zero-token rows are excluded so they can't pollute a mean or a resolve count.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import e3_bench as E3  # noqa: E402


def _row(model, cost, total, resolved):
    return {"model_requested": model, "cost_usd": cost, "total": total, "resolved": resolved,
            "model": model}


class SummarizeTest(unittest.TestCase):
    def test_cost_per_resolved_penalizes_failures(self):
        m = E3.MODELS[2]  # haiku
        rows = [_row(m, 0.10, 1000, True), _row(m, 0.10, 1000, False)]  # 2 runs, 1 resolved
        s = E3.summarize(rows)[m]
        self.assertEqual(s["runs"], 2)
        self.assertEqual(s["resolved"], 1)
        self.assertEqual(s["resolve_rate"], 0.5)
        self.assertAlmostEqual(s["cost_per_call"], 0.10)
        self.assertAlmostEqual(s["cost_per_resolved"], 0.20)  # $0.20 / 1 resolved, not / 2 runs

    def test_zero_token_rows_excluded(self):
        m = E3.MODELS[0]
        rows = [_row(m, 0.5, 1000, True), _row(m, 0.0, 0, False)]  # second = empty/failed call
        s = E3.summarize(rows)[m]
        self.assertEqual(s["runs"], 1)              # the zero-token row is not counted
        self.assertAlmostEqual(s["total_cost_usd"], 0.5)

    def test_models_are_isolated(self):
        rows = [_row(E3.MODELS[0], 0.6, 1000, True), _row(E3.MODELS[2], 0.08, 1000, True)]
        s = E3.summarize(rows)
        self.assertEqual(s[E3.MODELS[0]]["runs"], 1)
        self.assertEqual(s[E3.MODELS[2]]["runs"], 1)
        self.assertAlmostEqual(s[E3.MODELS[0]]["cost_per_resolved"], 0.6)
        self.assertAlmostEqual(s[E3.MODELS[2]]["cost_per_resolved"], 0.08)

    def test_no_resolved_gives_none_not_crash(self):
        m = E3.MODELS[1]
        s = E3.summarize([_row(m, 0.2, 1000, False)])[m]
        self.assertIsNone(s["cost_per_resolved"])
        self.assertEqual(s["resolve_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
