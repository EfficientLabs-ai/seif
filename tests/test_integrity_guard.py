"""unittest for the Integrity Guard (v0.2 WP-E)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import integrity_guard as IG

PROTECTED = ["tests/", "*/conftest.py", "test_*.py", "swebench/", ".github/workflows/", "pyproject.toml", "*.gold"]


class TestIntegrityGuard(unittest.TestCase):
    def test_clean_source_passes(self):
        d = "diff --git a/src/a.py b/src/a.py\n+++ b/src/a.py\n+x=1\n"
        ok, _ = IG.is_clean(d, PROTECTED); self.assertTrue(ok)

    def test_test_edit_hard(self):
        d = "diff --git a/tests/test_a.py b/tests/test_a.py\n+++ b/tests/test_a.py\n+assert True\n"
        ok, r = IG.is_clean(d, PROTECTED); self.assertFalse(ok); self.assertTrue(r["hard"])

    def test_dotpath_ci_hard(self):
        d = "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n+x\n"
        ok, _ = IG.is_clean(d, PROTECTED); self.assertFalse(ok)

    def test_nested_conftest_hard(self):
        d = "diff --git a/p/q/conftest.py b/p/q/conftest.py\n+++ b/p/q/conftest.py\n+x\n"
        ok, _ = IG.is_clean(d, PROTECTED); self.assertFalse(ok)

    def test_graded_id_flag_not_hard(self):
        d = "diff --git a/src/a.py b/src/a.py\n+++ b/src/a.py\n+ if x=='test_login': pass\n"
        ok, r = IG.is_clean(d, PROTECTED, ["tests/t.py::test_login"]); self.assertTrue(ok); self.assertTrue(r["flags"])


if __name__ == "__main__":
    unittest.main()
