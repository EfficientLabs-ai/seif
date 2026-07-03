"""unittest: seif_run must mint a chained receipt on EVERY terminal disposition, including the two legs
that used to leave a silent gap:

  - clean-room (checkpoint) creation itself fails (tmpfs exhaustion, bad base ref, git failure) — this used
    to raise BEFORE the receipted try-block, with NO receipt minted at all.
  - an operator abort (KeyboardInterrupt/SystemExit) during a run — the outer handler used to catch only
    Exception, so an abort skipped the receipt entirely.

Also pins that a plain unexpected fault (e.g. the editor crashing) still receipts ERROR and discards the
worktree, unchanged from before. Hermetic: ledgers pinned to temp, no real claude, no network.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import seif_run as SR  # noqa: E402
import project_harness as H  # noqa: E402
import checkpoint as CP  # noqa: E402


def _hash_of(rec):
    """Recompute a receipt's chain hash the way _receipt does (prev + sorted-json of all but 'h')."""
    return hashlib.sha256(
        (rec["prev"] + json.dumps({k: v for k, v in rec.items() if k != "h"}, sort_keys=True)).encode()
    ).hexdigest()[:16]


class SeifRunErrorReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-errrcpt-")
        self._h, self._l, self._f = H.RECEIPTS, CP.LEDGER, CP.FAILURES
        H.RECEIPTS = os.path.join(self.tmp, "r.jsonl")
        CP.LEDGER = os.path.join(self.tmp, "c.jsonl")
        CP.FAILURES = os.path.join(self.tmp, "f.jsonl")
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "calc.py"), "w").write("def add(a, b):\n    return a - b\n")  # bug
        open(os.path.join(self.repo, "test_calc.py"), "w").write(
            "import unittest\nfrom calc import add\n"
            "class T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(add(2, 3), 5)\n")
        g = lambda *a: subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True)
        g("add", "-A"); g("commit", "-qm", "base")
        self.cmd = f"{sys.executable} -m unittest -q test_calc"
        self._orig_claude_edit = SR._claude_edit
        self._orig_checkpoint = SR.H.checkpoint

    def tearDown(self):
        SR._claude_edit = self._orig_claude_edit
        SR.H.checkpoint = self._orig_checkpoint
        H.RECEIPTS, CP.LEDGER, CP.FAILURES = self._h, self._l, self._f
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _receipts(self):
        with open(H.RECEIPTS) as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def test_checkpoint_failure_mints_single_chained_error_receipt(self):
        with mock.patch.object(SR.H, "checkpoint", side_effect=OSError("disk full simulation")):
            with self.assertRaises(OSError):
                SR.seif_run(self.repo, "task", "true", budget=1, make_pr=False)
        recs = self._receipts()
        self.assertEqual(len(recs), 1, "exactly one receipt must be appended")
        rec = recs[0]
        self.assertEqual(rec["outcome"], "error")
        self.assertEqual(rec["final_outcome"], "ERROR")
        self.assertIn("clean-room checkpoint failed", rec["evidence_result"])
        self.assertEqual(rec["attempt_number"], 0)
        self.assertEqual(rec["prev"], "0" * 16)                  # first record in the (temp) chain
        self.assertEqual(rec["h"], _hash_of(rec))                # hash chain is correct

    def test_editor_crash_mints_error_receipt_and_discards_worktree(self):
        def boom(wt, *a, **k):
            raise RuntimeError("editor crashed")
        with mock.patch.object(SR, "_claude_edit", side_effect=boom):
            with self.assertRaises(RuntimeError):
                SR.seif_run(self.repo, "task", self.cmd, budget=1, make_pr=False, route=False)
        recs = self._receipts()
        rec = recs[-1]
        self.assertEqual(rec["final_outcome"], "ERROR")
        self.assertIn("RuntimeError", rec["evidence_result"])
        wt_list = subprocess.run(["git", "-C", self.repo, "worktree", "list"],
                                 capture_output=True, text=True).stdout.strip().splitlines()
        self.assertEqual(len(wt_list), 1, "only the main worktree may remain after discard")

    def test_abort_during_run_mints_abort_receipt(self):
        def interrupt(wt, *a, **k):
            raise KeyboardInterrupt()
        with mock.patch.object(SR, "_claude_edit", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                SR.seif_run(self.repo, "task", self.cmd, budget=1, make_pr=False, route=False)
        recs = self._receipts()
        rec = recs[-1]
        self.assertEqual(rec["final_outcome"], "ABORT")


if __name__ == "__main__":
    unittest.main()
