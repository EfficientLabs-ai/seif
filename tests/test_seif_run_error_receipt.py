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

    def test_abort_during_checkpoint_creation_mints_abort_receipt(self):
        # Codex, closed: the checkpoint try/except previously caught only Exception, so an operator abort
        # landing during clean-room creation itself — the exact scenario this PR's title claims to close —
        # left ZERO receipts (worse than the plain-Exception case above, which was already fixed once).
        with mock.patch.object(SR.H, "checkpoint", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                SR.seif_run(self.repo, "task", "true", budget=1, make_pr=False)
        recs = self._receipts()
        self.assertEqual(len(recs), 1, "exactly one receipt must be appended")
        rec = recs[0]
        self.assertEqual(rec["final_outcome"], "ABORT", "an interrupt is ABORT, not ERROR — same distinction the outer handler already makes")
        self.assertIn("clean-room checkpoint failed", rec["evidence_result"])

    def test_late_abort_after_accepted_receipt_does_not_mint_contradictory_second_receipt(self):
        # Codex P1, closed: an operator abort (or any error) during the POST-accept, best-effort PR-push
        # step previously escaped to the outer `except BaseException`, which minted a SECOND, contradictory
        # ABORT receipt on top of the just-written ACCEPTED_PR one and discarded the worktree — directly
        # violating this segment's own "best-effort and ISOLATED... must NEVER reach the outer discard"
        # contract. It must now be handled locally: exactly one receipt (ACCEPTED_PR), no re-raise, the
        # worktree survives, and seif_run returns its normal accepted result.
        bare = os.path.join(self.tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        subprocess.run(["git", "-C", self.repo, "remote", "add", "origin", bare], check=True)

        def fix(wt, *a, **k):
            open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
            return 0, SR.UM.empty()

        real_run = subprocess.run

        def push_interrupts(cmd, *a, **k):
            if isinstance(cmd, list) and "push" in cmd:
                raise KeyboardInterrupt()
            return real_run(cmd, *a, **k)

        with mock.patch.object(SR, "_claude_edit", side_effect=fix):
            with mock.patch.object(SR.subprocess, "run", side_effect=push_interrupts):
                result = SR.seif_run(self.repo, "task", self.cmd, budget=1, make_pr=True, route=False)

        self.assertTrue(result["accepted"], result)
        self.assertTrue(result.get("landed") is False)
        self.assertIn("branch and receipt are safe", result.get("pr") or "")
        recs = self._receipts()
        self.assertEqual(len(recs), 1, "exactly ONE receipt — no second, contradictory ABORT receipt on top of ACCEPTED_PR")
        self.assertEqual(recs[0]["final_outcome"], "ACCEPTED_PR")
        wt_list = subprocess.run(["git", "-C", self.repo, "worktree", "list"],
                                 capture_output=True, text=True).stdout.strip().splitlines()
        self.assertEqual(len(wt_list), 2, "the worktree must NOT be discarded — the accepted work survives (main + the accepted worktree)")

    def test_late_abort_during_cache_store_does_not_mint_contradictory_second_receipt(self):
        # Codex, round 2, closed: the first fix only widened the push/gh-create block's OWN except to
        # BaseException. The result-cache store block sits in the SAME post-ACCEPTED_PR-receipt region
        # with the identical exposure (its own except was still `Exception` only) — an interrupt there
        # must ALSO be absorbed by the region's outer handler, not escape to the outer discard-and-
        # double-receipt handler.
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
        import result_cache as RC  # noqa: E402
        rcache = RC.ResultCache(path=os.path.join(self.tmp, "cache.json"))

        def fix(wt, *a, **k):
            open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
            return 0, SR.UM.empty()

        with mock.patch.object(SR, "_claude_edit", side_effect=fix):
            with mock.patch.object(rcache, "store", side_effect=KeyboardInterrupt()):
                result = SR.seif_run(self.repo, "task", self.cmd, budget=1, make_pr=False, route=False,
                                     result_cache=rcache)

        self.assertTrue(result["accepted"], result)
        self.assertIn("branch and receipt are safe", result.get("pr") or "")
        recs = self._receipts()
        self.assertEqual(len(recs), 1, "exactly ONE receipt — a cache-store interrupt must not mint a second, contradictory ABORT receipt")
        self.assertEqual(recs[0]["final_outcome"], "ACCEPTED_PR")

    def test_late_abort_during_has_remote_check_does_not_mint_contradictory_second_receipt(self):
        # Codex, round 2, closed: _has_remote(repo) ran BEFORE any try block at all — an interrupt there
        # had no local handler whatsoever and went straight to the outer discard-and-double-receipt path.
        def fix(wt, *a, **k):
            open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
            return 0, SR.UM.empty()

        with mock.patch.object(SR, "_claude_edit", side_effect=fix):
            with mock.patch.object(SR, "_has_remote", side_effect=KeyboardInterrupt()):
                result = SR.seif_run(self.repo, "task", self.cmd, budget=1, make_pr=True, route=False)

        self.assertTrue(result["accepted"], result)
        self.assertIn("branch and receipt are safe", result.get("pr") or "")
        recs = self._receipts()
        self.assertEqual(len(recs), 1, "exactly ONE receipt — an interrupt during the has_remote check must not mint a second, contradictory ABORT receipt")
        self.assertEqual(recs[0]["final_outcome"], "ACCEPTED_PR")


if __name__ == "__main__":
    unittest.main()
