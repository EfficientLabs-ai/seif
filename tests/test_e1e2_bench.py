"""unittest for the E1/E2 token-economics bench (logos/e1e2_bench.py) — pure logic, no real claude.

Pins the parts a measurement must get right: the forward-dependency closure used by E2 (the scope hint),
the fixture builds a real repo whose multi-hop tests fail before any fix, the same-model pairing in
summarize (so a model confound can't sneak into a 'clean' ratio), and the cache-excluding cost floor.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import e1e2_bench as E  # noqa: E402


class ForwardClosureTest(unittest.TestCase):
    def test_multi_hop_closure_reaches_root_cause(self):
        # the failing test points at api.py; the bug is 2 hops up in core.py — the scope must include it
        self.assertEqual(E.forward_closure("deep/api.py"), ["deep/api.py", "deep/core.py", "deep/ops.py"])
        self.assertEqual(E.forward_closure("deep/alpha.py"), ["deep/alpha.py", "deep/beta.py", "deep/gamma.py"])

    def test_unknown_file_returns_just_itself(self):
        self.assertEqual(E.forward_closure("deep/nonexistent.py"), ["deep/nonexistent.py"])


class FixtureTest(unittest.TestCase):
    def test_multi_hop_tests_fail_before_fix(self):
        repo = E.build_fixture(tempfile.mkdtemp(prefix="t-e1e2-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(repo, ignore_errors=True))
        self.assertTrue(os.path.exists(os.path.join(repo, "graphify-out", "graph.json")))
        self.assertTrue(os.path.exists(os.path.join(repo, ".gitignore")))
        for mod in ("tests.test_api", "tests.test_alpha"):
            p = subprocess.run([sys.executable, "-m", "unittest", mod], cwd=repo, capture_output=True)
            self.assertNotEqual(p.returncode, 0, f"{mod} must fail before the root-cause fix")


class SummarizeTest(unittest.TestCase):
    def test_only_same_model_resolved_pairs_count(self):
        pairs = [
            # clean: both opus, both resolved → counts
            {"a": {"model": "opus", "resolved": True, "input_tokens": 100, "total": 1000, "cost_usd": 0.5,
                   "output_tokens": 10, "cache_creation_input_tokens": 40, "cache_read_input_tokens": 200},
             "b": {"model": "opus", "resolved": True, "input_tokens": 50, "total": 600, "cost_usd": 0.3,
                   "output_tokens": 8, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 120}},
            # confounded: different models → excluded
            {"a": {"model": "opus", "resolved": True, "input_tokens": 100, "total": 1000, "cost_usd": 0.5,
                   "output_tokens": 10, "cache_creation_input_tokens": 40, "cache_read_input_tokens": 200},
             "b": {"model": "haiku", "resolved": True, "input_tokens": 50, "total": 600, "cost_usd": 0.1,
                   "output_tokens": 8, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 120}},
        ]
        s = E.summarize(pairs, "a", "b")
        self.assertEqual(s["n_clean_pairs"], 1)            # the haiku pair is excluded
        self.assertEqual(s["fresh_input_ratio"][0], 0.5)   # 50/100 from the clean pair only

    def test_cost_excl_cache_read_floor(self):
        # real-money floor = input*5 + output*25 + cache_create*6.25 per MTok (cache_read excluded)
        u = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 9_999_999}
        self.assertEqual(E.cost_excl_cache_read(u), 5.0)   # cache_read does not move the floor


if __name__ == "__main__":
    unittest.main()
