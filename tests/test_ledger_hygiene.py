"""Regression test: this repo's own unittest suite must add ZERO lines to the PRODUCTION ledgers
(project_harness.RECEIPTS, seif_loop.FOUNDER_QUEUE). Both are captured HERE, at import time — before
any other test module's setUp has a chance to redirect them — so this test proves the REAL production
paths stay untouched, not a value some other test already swapped in.

Each of the three previously-leaking suites is run in its OWN subprocess (never the full suite here,
which would recurse into this test file via discovery).
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import project_harness as H  # noqa: E402
import seif_loop as SL       # noqa: E402

# Captured BEFORE any test redirect — the real production ledger paths.
_PRODUCTION_RECEIPTS = H.RECEIPTS
_PRODUCTION_FOUNDER_QUEUE = SL.FOUNDER_QUEUE

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_LEAKING_SUITES = (
    "test_controller.py",
    "test_project_harness_cleanroom.py",
    "test_seif_run_restore.py",
)


def _line_count(path):
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        return sum(1 for _ in f)


class LedgerHygieneTest(unittest.TestCase):
    def test_previously_leaking_suites_add_zero_lines_to_production_ledgers(self):
        before_receipts = _line_count(_PRODUCTION_RECEIPTS)
        before_queue = _line_count(_PRODUCTION_FOUNDER_QUEUE)

        for pattern in _LEAKING_SUITES:
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern],
                cwd=_REPO_ROOT, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(proc.returncode, 0,
                             f"{pattern} must pass in isolation:\n{proc.stdout}\n{proc.stderr}")

        after_receipts = _line_count(_PRODUCTION_RECEIPTS)
        after_queue = _line_count(_PRODUCTION_FOUNDER_QUEUE)
        self.assertEqual(after_receipts, before_receipts,
                         f"production receipts ledger grew: {_PRODUCTION_RECEIPTS}")
        self.assertEqual(after_queue, before_queue,
                         f"production founder queue grew: {_PRODUCTION_FOUNDER_QUEUE}")


if __name__ == "__main__":
    unittest.main()
