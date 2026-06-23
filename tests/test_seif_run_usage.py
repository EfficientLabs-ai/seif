"""unittest for token instrumentation wired into the loop (seif_run + project_harness).

Pins: (1) the chokepoint `_claude_edit` now returns (rc, usage) parsed from the `--output-format json`
envelope; (2) `_receipt(..., usage=...)` writes a cost-attributable receipt that still hash-chains;
(3) backward compatibility — a receipt minted WITHOUT usage has no `usage` key and still chains, so
existing callers and the 86 historical receipts are unaffected.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import project_harness as H  # noqa: E402
import seif_run  # noqa: E402

_ENVELOPE = json.dumps({
    "model": "claude-opus-4-8", "total_cost_usd": 0.05,
    "usage": {"input_tokens": 100, "output_tokens": 20,
              "cache_creation_input_tokens": 5, "cache_read_input_tokens": 50},
})


class ClaudeEditUsageTest(unittest.TestCase):
    def test_claude_edit_returns_rc_and_parsed_usage(self):
        fake = mock.Mock(returncode=0, stdout=_ENVELOPE, stderr="")
        with mock.patch.object(seif_run.subprocess, "run", return_value=fake) as run:
            rc, usage = seif_run._claude_edit("/tmp", "do a thing", "", True, 5)
        self.assertEqual(rc, 0)
        self.assertEqual(usage["input_tokens"], 100)
        self.assertEqual(usage["cost_usd"], 0.05)
        # the invocation must request the JSON envelope (else there is nothing to meter)
        argv = run.call_args.args[0]
        self.assertIn("--output-format", argv)
        self.assertIn("json", argv)

    def test_claude_edit_timeout_returns_zeroed_usage_not_crash(self):
        with mock.patch.object(seif_run.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)):
            rc, usage = seif_run._claude_edit("/tmp", "t", "", True, 5)
        self.assertIsNone(rc)
        self.assertEqual(usage["input_tokens"], 0)
        self.assertEqual(usage["cost_usd"], 0.0)

    def test_retry_on_empty_envelope_then_succeeds(self):
        # an empty (zero-token) envelope is an infra hiccup → retry, not "no change". 2 empty then 1 real.
        empty = mock.Mock(returncode=0, stdout='{"usage":{"input_tokens":0}}', stderr="")
        real = mock.Mock(returncode=0, stdout=_ENVELOPE, stderr="")
        with mock.patch.object(seif_run.subprocess, "run", side_effect=[empty, empty, real]) as run:
            rc, usage = seif_run._claude_edit("/tmp", "t", "", True, 5)
        self.assertEqual(usage["input_tokens"], 100)      # got the real call's usage after 2 retries
        self.assertEqual(run.call_count, 3)

    def test_retry_on_empty_gives_up_after_three(self):
        empty = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(seif_run.subprocess, "run", return_value=empty) as run:
            rc, usage = seif_run._claude_edit("/tmp", "t", "", True, 5)
        self.assertEqual(usage["input_tokens"], 0)        # still empty → caller treats as no_change
        self.assertEqual(run.call_count, 3)               # bounded

    def test_model_flag_passed_when_pinned(self):
        fake = mock.Mock(returncode=0, stdout=_ENVELOPE, stderr="")
        with mock.patch.object(seif_run.subprocess, "run", return_value=fake) as run:
            seif_run._claude_edit("/tmp", "t", "", True, 5, model="claude-opus-4-8")
        argv = run.call_args.args[0]
        self.assertIn("--model", argv)
        self.assertIn("claude-opus-4-8", argv)

    def test_no_model_flag_by_default(self):
        fake = mock.Mock(returncode=0, stdout=_ENVELOPE, stderr="")
        with mock.patch.object(seif_run.subprocess, "run", return_value=fake) as run:
            seif_run._claude_edit("/tmp", "t", "", True, 5)
        self.assertNotIn("--model", run.call_args.args[0])


class ReceiptUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-rcpt-")
        self._orig = H.RECEIPTS
        H.RECEIPTS = os.path.join(self.tmp, "receipts.jsonl")

    def tearDown(self):
        H.RECEIPTS = self._orig

    def _last_line(self):
        with open(H.RECEIPTS) as f:
            return json.loads([ln for ln in f if ln.strip()][-1])

    def test_receipt_with_usage_includes_field_and_chains(self):
        spend = {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 5,
                 "cache_read_input_tokens": 50, "cost_usd": 0.05, "calls": 1, "model": "claude-opus-4-8"}
        rec = H._receipt("/repo", "task", "pytest", {"exit_code": 0, "outcome": "pass"}, "diff", usage=spend)
        self.assertEqual(rec["usage"], spend)
        self.assertEqual(len(rec["h"]), 16)
        # the usage is covered by the integrity hash (recompute and compare)
        import hashlib
        expected = hashlib.sha256(
            (rec["prev"] + json.dumps({k: v for k, v in rec.items() if k != "h"}, sort_keys=True)).encode()
        ).hexdigest()[:16]
        self.assertEqual(rec["h"], expected)
        self.assertEqual(self._last_line()["usage"]["input_tokens"], 100)

    def test_receipt_without_usage_is_backward_compatible(self):
        rec = H._receipt("/repo", "task", "pytest", {"exit_code": 0, "outcome": "pass"}, "diff")
        self.assertNotIn("usage", rec)            # no key when not provided — old shape preserved
        self.assertEqual(len(rec["h"]), 16)       # still chains

    def test_usage_and_no_usage_receipts_chain_together(self):
        r1 = H._receipt("/repo", "t1", "pytest", {"exit_code": 0, "outcome": "pass"}, "d1")
        r2 = H._receipt("/repo", "t2", "pytest", {"exit_code": 0, "outcome": "pass"}, "d2",
                        usage={"input_tokens": 1, "cost_usd": 0.0, "calls": 1})
        self.assertEqual(r2["prev"], r1["h"])     # the chain survives a mixed (old/new) shape


if __name__ == "__main__":
    unittest.main()
