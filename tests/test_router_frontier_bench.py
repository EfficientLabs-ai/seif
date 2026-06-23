"""unittest for the router/frontier bench (logos/router_frontier_bench.py) — derive_strategies logic.

The live run had Haiku resolve everything, so escalation never triggered. These tests use a SYNTHETIC
matrix where Haiku FAILS, to prove the derivation logic is correct (escalation accumulates cost + escalates
on a visible-gate failure; static-route picks per class; false-accepts counted from the withheld oracle).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import router_frontier_bench as R  # noqa: E402

H, S, O = R.HAIKU, R.SONNET, R.OPUS


def _row(task, cls, seed, model, visible, hidden, cost):
    return {"task": task, "cls": cls, "seed": seed, "model": model, "visible": visible, "hidden": hidden,
            "resolved": visible and hidden, "false_accept": visible and not hidden, "cost_usd": cost}


class DeriveTest(unittest.TestCase):
    def _matrix_one_task(self, tid, cls, haiku, sonnet, opus):
        # haiku/sonnet/opus = (visible, hidden, cost) for seed 0
        return [_row(tid, cls, 0, H, *haiku), _row(tid, cls, 0, S, *sonnet), _row(tid, cls, 0, O, *opus)]

    def test_escalation_escalates_on_gate_failure(self):
        # haiku FAILS the gate, sonnet passes → escalation tries haiku then sonnet, cost = haiku+sonnet
        m = self._matrix_one_task("t", "hard", (False, False, 0.10), (True, True, 0.25), (True, True, 0.70))
        s = R.derive_strategies(m)
        e = s["escalation"]
        self.assertEqual(e["resolved"], 1)
        self.assertAlmostEqual(e["cost_per_resolved"], 0.35)   # haiku 0.10 + sonnet 0.25
        self.assertEqual(e["resolver_mix"], {"sonnet": 1})
        self.assertEqual(e["mean_attempts"], 2.0)
        # always:haiku failed this task
        self.assertEqual(s["always:haiku"]["resolved"], 0)

    def test_escalation_accepts_on_gate_but_oracle_catches_false_accept(self):
        # haiku PASSES the visible gate but FAILS the hidden oracle → router accepts haiku (gate), but it's a
        # FALSE ACCEPT; escalation stops at haiku (gate passed), resolved=False, false_accept counted.
        m = self._matrix_one_task("t", "hard", (True, False, 0.10), (True, True, 0.25), (True, True, 0.70))
        s = R.derive_strategies(m)
        e = s["escalation"]
        self.assertEqual(e["resolved"], 0)
        self.assertEqual(e["false_accepts"], 1)
        self.assertEqual(e["resolver_mix"], {"haiku": 1})     # accepted on the gate, wrongly

    def test_static_route_picks_model_per_class(self):
        # CLASS_ROUTE: medium→haiku, hard→opus. A hard task routes to opus.
        m = self._matrix_one_task("t", "hard", (True, True, 0.10), (True, True, 0.25), (True, True, 0.70))
        s = R.derive_strategies(m)
        self.assertAlmostEqual(s["static-route"]["cost_per_resolved"], 0.70)   # routed to opus

    def test_always_strategies_isolated(self):
        m = self._matrix_one_task("t", "medium", (True, True, 0.09), (True, True, 0.22), (True, True, 0.60))
        s = R.derive_strategies(m)
        self.assertAlmostEqual(s["always:haiku"]["cost_per_resolved"], 0.09)
        self.assertAlmostEqual(s["always:opus"]["cost_per_resolved"], 0.60)


if __name__ == "__main__":
    unittest.main()
