"""unittest for seif_run._resolve_base — resolving the clean-room base to the last HEALTHY checkpoint."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import checkpoint as CP  # noqa: E402
import seif_run as SR    # noqa: E402


class ResolveBaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-seif-restore-")
        CP.LEDGER = os.path.join(self.tmp, "cp.jsonl")          # temp registry — never touch the real ledger
        CP.FAILURES = os.path.join(self.tmp, "fail.jsonl")
        self.repo = os.path.join(self.tmp, "repo")
        self._g = lambda *a: subprocess.run(
            ["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
            check=True, capture_output=True)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
        self._g("add", "-A"); self._g("commit", "-qm", "c1")
        self.c1 = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()

    def _commit(self, body, msg):
        open(os.path.join(self.repo, "calc.py"), "w").write(body)
        self._g("add", "-A"); self._g("commit", "-qm", msg)
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()

    def test_resolve_last_healthy_to_checkpoint_commit(self):
        # checkpoint the verified state at C1, then advance HEAD to C2
        CP.create(self.repo, "c1 healthy", commit=self.c1,
                  proof={"outcome": "pass", "receipt": "r1"},
                  context={"task": "impl add", "files_changed": ["calc.py"]})
        self._commit("def add(a, b):\n    return a + b\ndef sub(a, b):\n    return a - b\n", "c2")
        # 'last-healthy' resolves to the checkpoint's commit (C1), not HEAD (C2)
        self.assertEqual(SR._resolve_base(self.repo, "last-healthy"), self.c1)
        # the default 'HEAD' is returned byte-identical (unchanged)
        self.assertEqual(SR._resolve_base(self.repo, "HEAD"), "HEAD")

    def test_resolve_last_healthy_no_checkpoints_falls_back_to_head(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.assertEqual(SR._resolve_base(other, "last-healthy"), "HEAD")

    def test_arbitrary_base_unchanged(self):
        self.assertEqual(SR._resolve_base(self.repo, "main"), "main")
        self.assertEqual(SR._resolve_base(self.repo, self.c1), self.c1)


if __name__ == "__main__":
    unittest.main()
