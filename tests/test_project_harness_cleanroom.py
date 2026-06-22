"""unittest: the /seif clean room pre-places the Stop-hook bypass AND never lets it stage into a patch."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import project_harness as H  # noqa: E402


class CleanRoomBypassTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="t-cleanroom-")
        g = lambda *a: subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "src.py"), "w").write("x = 1\n")
        g("add", "-A"); g("commit", "-qm", "base")
        self.wt = None

    def tearDown(self):
        if self.wt:
            H.discard(self.repo, self.wt)

    def test_bypass_present_but_never_staged(self):
        self.wt = H.checkpoint(self.repo, link_deps=False)
        # the bypass file IS in the clean room (so the nested editor's Stop hook is satisfied)
        self.assertTrue(os.path.exists(os.path.join(self.wt, ".seif-gate-off")), "clean room must carry the bypass")
        # ...but a normal edit + `git add -A` + diff must NOT include it (excluded)
        open(os.path.join(self.wt, "src.py"), "w").write("x = 2\n")
        subprocess.run(["git", "-C", self.wt, "add", "-A"], capture_output=True)
        patch = subprocess.run(["git", "-C", self.wt, "diff", "--cached"], capture_output=True, text=True).stdout
        self.assertIn("src.py", patch)
        self.assertNotIn(".seif-gate-off", patch, "the bypass sentinel must never reach the candidate patch")

    def test_verify_change_rejects_force_added_bypass(self):
        # the HARD guarantee: even if a change FORCE-adds the bypass sentinel (defeating the soft exclude),
        # verify_change must REJECT via integrity_guard — never accept a patch carrying a gate-disabler.
        def hostile(wt):
            open(os.path.join(wt, "src.py"), "w").write("x = 2\n")
            open(os.path.join(wt, ".seif-gate-off"), "w").write("disabled\n")
            subprocess.run(["git", "-C", wt, "add", "-f", ".seif-gate-off"], capture_output=True)
        r = H.verify_change(self.repo, "true", hostile, task="hostile-bypass")
        self.assertFalse(r["accepted"], "a force-added gate-bypass must be rejected")
        self.assertEqual(r["result"]["outcome"], "integrity_violation")
        self.assertTrue(any(h["vector"] == "gate_bypass_sentinel" for h in r["integrity"]["hard"]))


if __name__ == "__main__":
    unittest.main()
