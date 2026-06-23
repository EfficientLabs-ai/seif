"""unittest for the E4 real-codebase bench (logos/e4_bench.py) — injection + escalation + composition.

Pins: inject() applies the exact break and refuses a missing anchor (so a measurement can't silently run
on un-broken code); escalate() stops at the first resolver and accumulates cost; composition() computes
the cached-environment share. Real model calls are mocked.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import e4_bench as E  # noqa: E402


class InjectTest(unittest.TestCase):
    def _wt_with(self, rel, text):
        wt = tempfile.mkdtemp(prefix="t-e4-")
        self.addCleanup(lambda: __import__("shutil").rmtree(wt, ignore_errors=True))
        p = os.path.join(wt, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)
        return wt

    def test_inject_applies_the_break(self):
        bug = E.BUGS[1]  # e4_chore: '        ctype = "chore"' -> '        pass'
        wt = self._wt_with(bug["file"], "def x():\n" + bug["old"] + "\n")
        E.inject(wt, bug)
        out = open(os.path.join(wt, bug["file"])).read()
        self.assertIn(bug["new"], out)
        self.assertNotIn(bug["old"], out)

    def test_inject_refuses_missing_anchor(self):
        bug = E.BUGS[1]
        wt = self._wt_with(bug["file"], "no anchor here\n")
        with self.assertRaises(AssertionError):       # must not run on un-broken code
            E.inject(wt, bug)


class EscalationTest(unittest.TestCase):
    def _r(self, resolved, cost):
        return {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0, "cost_usd": cost, "model": None, "resolved": resolved}

    def test_stops_at_first_resolver(self):
        seq = iter([self._r(False, 0.10), self._r(True, 0.20)])
        with mock.patch.object(E, "one_call", side_effect=lambda *a, **k: next(seq)):
            e = E.escalate(E.BUGS[0])
        self.assertEqual(e["resolver"], E.SONNET)
        self.assertEqual(len(e["attempts"]), 2)
        self.assertAlmostEqual(e["cost_usd"], 0.30)


class CompositionTest(unittest.TestCase):
    def test_env_share(self):
        u = {"input_tokens": 100, "output_tokens": 0,
             "cache_creation_input_tokens": 300, "cache_read_input_tokens": 600}
        self.assertAlmostEqual(E.composition(u), 0.9)   # (300+600)/1000
        self.assertIsNone(E.composition({"input_tokens": 0, "output_tokens": 0,
                                         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}))


if __name__ == "__main__":
    unittest.main()
