"""unittest for seif_run's PR-creation hygiene: stacked-PR base resolution + title truncation.

Why these exist: a run cut from a feature branch used to open its PR against the DEFAULT
branch (gh pr create with no --base), so the PR showed the whole parent diff, misstated its
scope, and inherited every parent conflict — efficientlabs-web#35 ("create ONE new file",
33 files changed) was this bug. And task[:64] sheared titles mid-word.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import seif_run as SR


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True)


class PrBaseBranchTest(unittest.TestCase):
    """Exercises _pr_base_branch against a real (temp) repo with a real 'origin' remote."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.origin = os.path.join(root, "origin.git")
        self.repo = os.path.join(root, "repo")
        subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", self.origin],
                       check=True, capture_output=True)
        subprocess.run(["git", "clone", "-q", self.origin, self.repo], check=True, capture_output=True)
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        _git(self.repo, "checkout", "-q", "-b", "main")
        with open(os.path.join(self.repo, "f"), "w") as fh:
            fh.write("x")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        _git(self.repo, "push", "-q", "-u", "origin", "main")
        # make origin/HEAD known, as a real clone would have it
        _git(self.repo, "remote", "set-head", "origin", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_branch_yields_none(self):
        # cut from main → no --base needed (default flow)
        self.assertIsNone(SR._pr_base_branch(self.repo, "HEAD"))
        self.assertIsNone(SR._pr_base_branch(self.repo, "main"))

    def test_feature_branch_on_remote_is_the_stacked_base(self):
        _git(self.repo, "checkout", "-q", "-b", "feat/parent")
        with open(os.path.join(self.repo, "g"), "w") as fh:
            fh.write("y")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "parent work")
        _git(self.repo, "push", "-q", "-u", "origin", "feat/parent")
        self.assertEqual(SR._pr_base_branch(self.repo, "HEAD"), "feat/parent")
        self.assertEqual(SR._pr_base_branch(self.repo, "feat/parent"), "feat/parent")

    def test_local_only_branch_yields_none(self):
        # a base branch that does not exist on the remote cannot be a PR base
        _git(self.repo, "checkout", "-q", "-b", "feat/local-only")
        self.assertIsNone(SR._pr_base_branch(self.repo, "HEAD"))

    def test_detached_head_yields_none(self):
        sha = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        _git(self.repo, "checkout", "-q", "--detach", sha)
        self.assertIsNone(SR._pr_base_branch(self.repo, "HEAD"))

    def test_commit_sha_base_yields_none(self):
        # 'last-healthy' resolves to a commit sha before PR time — sha is not a branch
        sha = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertIsNone(SR._pr_base_branch(self.repo, sha))

    def test_never_raises_on_garbage(self):
        self.assertIsNone(SR._pr_base_branch("/nonexistent/path", "HEAD"))


class PrTitleSubjectTest(unittest.TestCase):
    def test_short_task_passes_through(self):
        self.assertEqual(SR._pr_title_subject("fix the widget"), "fix the widget")

    def test_long_task_truncates_at_word_boundary_with_ellipsis(self):
        task = ("Create ONE new file, tests/stripe-fail-closed.test.mjs "
                "(create the tests and nothing else whatsoever)")
        t = SR._pr_title_subject(task)
        self.assertLessEqual(len(t), 65)
        self.assertTrue(t.endswith("…"))
        self.assertNotIn("(create t", t)          # the historical mid-word shear
        self.assertFalse(t[:-1].endswith(" "))    # no dangling space before the ellipsis

    def test_multiline_task_uses_first_line_only(self):
        self.assertEqual(SR._pr_title_subject("headline\nbody line two"), "headline")

    def test_empty_task_is_empty(self):
        self.assertEqual(SR._pr_title_subject(""), "")
        self.assertEqual(SR._pr_title_subject(None), "")


if __name__ == "__main__":
    unittest.main()
