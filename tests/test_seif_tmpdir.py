"""unittest: SEIF clean-room worktrees are disk-backed by default (SEIF_TMPDIR override), not /tmp tmpfs."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import project_harness as H  # noqa: E402


class SeifTmpdirTest(unittest.TestCase):
    def setUp(self):
        self._had_env = "SEIF_TMPDIR" in os.environ
        self._orig_env = os.environ.get("SEIF_TMPDIR")
        self.repo = tempfile.mkdtemp(prefix="t-tmpdir-")
        g = lambda *a: subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "src.py"), "w").write("x = 1\n")
        g("add", "-A"); g("commit", "-qm", "base")
        self.wt = None

    def tearDown(self):
        if self.wt:
            H.discard(self.repo, self.wt)
        if self._had_env:
            os.environ["SEIF_TMPDIR"] = self._orig_env
        else:
            os.environ.pop("SEIF_TMPDIR", None)

    def test_checkpoint_honors_seif_tmpdir_override(self):
        override = tempfile.mkdtemp(prefix="t-override-")
        os.environ["SEIF_TMPDIR"] = override
        self.wt = H.checkpoint(self.repo, link_deps=False)
        self.assertTrue(os.path.realpath(self.wt).startswith(os.path.realpath(override)),
                         f"worktree {self.wt} should live inside SEIF_TMPDIR override {override}")

    def test_default_seif_tmpdir_is_home_dot_seif_tmp(self):
        os.environ.pop("SEIF_TMPDIR", None)
        expected = os.path.expanduser("~/.seif/tmp")
        result = H._seif_tmpdir()
        self.assertEqual(result, expected)
        self.assertTrue(os.path.isdir(expected))

    def test_uncreatable_seif_tmpdir_falls_back_to_system_default(self):
        blocker = tempfile.NamedTemporaryFile(delete=False)
        blocker.close()
        try:
            os.environ["SEIF_TMPDIR"] = os.path.join(blocker.name, "tmp")
            self.assertIsNone(H._seif_tmpdir(), "a dir under a regular file can't be created; must degrade to None")
            self.wt = H.checkpoint(self.repo, link_deps=False)
            self.assertTrue(os.path.isdir(self.wt), "checkpoint must still succeed via system-default fallback")
        finally:
            os.unlink(blocker.name)

    def test_toctou_mkdtemp_failure_after_seif_tmpdir_check_falls_back(self):
        # Codex Minor, closed: _seif_tmpdir()'s own os.makedirs() check can succeed and the directory
        # still be gone/unwritable by the time tempfile.mkdtemp() actually tries to create inside it
        # (removed, quota hit, permissions changed in between). checkpoint() must degrade to mkdtemp's
        # system default, not crash the gate — the docstring's "degrade, never crash" promise covers
        # this window too, not just _seif_tmpdir()'s own pre-check.
        vanished = tempfile.mkdtemp(prefix="t-vanish-")
        os.rmdir(vanished)  # exists at the moment _seif_tmpdir() would return it, gone by mkdtemp() time
        with patch.object(H, "_seif_tmpdir", return_value=vanished):
            self.wt = H.checkpoint(self.repo, link_deps=False)
        self.assertTrue(os.path.isdir(self.wt), "checkpoint must still succeed via system-default fallback")
        self.assertFalse(os.path.realpath(self.wt).startswith(os.path.realpath(vanished)),
                          "the worktree must NOT be under the vanished dir — it degraded to the system default")

    def test_worktree_is_functional_git_worktree(self):
        self.wt = H.checkpoint(self.repo, link_deps=False)
        self.assertTrue(os.path.isfile(os.path.join(self.wt, "src.py")), "worktree must contain tracked file")
        self.assertEqual(open(os.path.join(self.wt, "src.py")).read(), "x = 1\n")


if __name__ == "__main__":
    unittest.main()
