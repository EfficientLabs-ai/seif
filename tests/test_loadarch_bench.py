"""unittest for the load-architecture bench (logos/loadarch_bench.py) — decomposition + fixture.

Pins the honest decomposition: a source's cost = full − stripped-arm; a FAILED arm (e.g. `--bare` that
returned empty) yields None, never a bogus full−0 that would overstate the saving.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import loadarch_bench as L  # noqa: E402


class DecompositionTest(unittest.TestCase):
    def test_clean_decomposition(self):
        per_arm = {
            "full":   {"fresh_input": 31700},
            "noMCP":  {"fresh_input": 18100},   # full−noMCP = 13600 (MCP)
            "noUser": {"fresh_input": 14700},   # full−noUser = 17000 (user config)
            "bare":   {"fresh_input": 2500},    # full−bare = 29200 (total)
        }
        d = L.env_decomposition(per_arm)
        self.assertEqual(d["mcp_fresh_input"], 13600)
        self.assertEqual(d["user_config_fresh_input"], 17000)
        self.assertEqual(d["total_env_tax_fresh_input"], 29200)
        self.assertEqual(d["failed_arms"], [])

    def test_failed_bare_arm_yields_none_not_bogus_total(self):
        per_arm = {
            "full":   {"fresh_input": 31700},
            "noMCP":  {"fresh_input": 18100},
            "noUser": {"fresh_input": 14700},
            "bare":   {"fresh_input": None},    # --bare returned empty → FAILED
        }
        d = L.env_decomposition(per_arm)
        self.assertIsNone(d["total_env_tax_fresh_input"])   # NOT 31700−0
        self.assertEqual(d["failed_arms"], ["bare"])
        self.assertEqual(d["mcp_fresh_input"], 13600)       # the working arms still decompose


class FixtureTest(unittest.TestCase):
    def test_tasks_fail_before_fix(self):
        repo = L.build_fixture(tempfile.mkdtemp(prefix="t-r3-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(repo, ignore_errors=True))
        for tid, task, mod, _s, _sb, _tb in L.TASKS:
            p = subprocess.run([sys.executable, "-m", "unittest", mod], cwd=repo, capture_output=True)
            self.assertNotEqual(p.returncode, 0, f"{tid} must fail before fix")


if __name__ == "__main__":
    unittest.main()
