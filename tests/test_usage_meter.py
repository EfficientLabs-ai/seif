"""unittest for the token/cost meter (logos/usage_meter.py) — the cost-attribution primitive.

These pin the contract that makes a spend claim MEASURABLE: a real `claude -p --output-format json`
envelope parses to exact token classes + cost; anything malformed degrades to zeros (never raises into
the loop); accumulation sums classes, counts calls, and keeps the first model seen.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import usage_meter as UM  # noqa: E402

# A realistic `claude -p --output-format json` result envelope (fields the verifier confirmed live).
_ENVELOPE = json.dumps({
    "type": "result", "subtype": "success", "is_error": False,
    "result": "done", "model": "claude-opus-4-8", "num_turns": 3, "duration_ms": 4200,
    "total_cost_usd": 0.1234,
    "usage": {"input_tokens": 18569, "output_tokens": 412,
              "cache_creation_input_tokens": 900, "cache_read_input_tokens": 15333},
})


class ParseUsageTest(unittest.TestCase):
    def test_parses_real_envelope(self):
        u = UM.parse_usage(_ENVELOPE)
        self.assertEqual(u["input_tokens"], 18569)
        self.assertEqual(u["output_tokens"], 412)
        self.assertEqual(u["cache_creation_input_tokens"], 900)
        self.assertEqual(u["cache_read_input_tokens"], 15333)
        self.assertAlmostEqual(u["cost_usd"], 0.1234)
        self.assertEqual(u["model"], "claude-opus-4-8")

    def test_malformed_inputs_degrade_to_zero_never_raise(self):
        for bad in ["", "not json", "{partial", "[]", "null", "123", json.dumps({"no": "usage"})]:
            u = UM.parse_usage(bad)                       # must not raise
            self.assertEqual(UM.total_tokens({**UM.empty(), **u}), 0, f"expected zero tokens for {bad!r}")
            self.assertEqual(u["cost_usd"], 0.0)
            self.assertIsNone(u["model"])

    def test_model_read_from_modelusage_when_no_top_level_model(self):
        # real `claude -p` envelopes have no top-level `model`; the name is a key under `modelUsage`
        u = UM.parse_usage(json.dumps({
            "usage": {"input_tokens": 5}, "total_cost_usd": 0.01,
            "modelUsage": {"claude-opus-4-8": {"inputTokens": 5}}}))
        self.assertEqual(u["model"], "claude-opus-4-8")

    def test_partial_usage_fields_are_tolerated(self):
        u = UM.parse_usage(json.dumps({"usage": {"input_tokens": 10}}))   # only one field present
        self.assertEqual(u["input_tokens"], 10)
        self.assertEqual(u["output_tokens"], 0)

    def test_bool_is_not_counted_as_a_token(self):
        # bool is an int subclass in Python — a stray True must not become 1 token / $1
        u = UM.parse_usage(json.dumps({"usage": {"input_tokens": True}, "total_cost_usd": True}))
        self.assertEqual(u["input_tokens"], 0)
        self.assertEqual(u["cost_usd"], 0.0)

    def test_nonfinite_and_overflow_numbers_do_not_raise(self):
        # JSON-valid but pathological values (Infinity/NaN, 1e309 → inf) must degrade to zero, never raise
        # int(inf) raises OverflowError — the meter must never let that escape into the loop.
        for payload in ['{"usage":{"input_tokens":1e309},"total_cost_usd":1e309}',
                        '{"usage":{"input_tokens":Infinity,"output_tokens":NaN}}',
                        '{"usage":{"input_tokens":-Infinity}}']:
            u = UM.parse_usage(payload)                 # must not raise
            self.assertEqual(u["input_tokens"], 0)
            self.assertEqual(u["output_tokens"], 0)
            self.assertEqual(u["cost_usd"], 0.0)
        # and the same value must be safe through accumulate()
        acc = UM.empty()
        UM.accumulate(acc, {"input_tokens": float("inf"), "cost_usd": float("nan")})
        self.assertEqual(acc["input_tokens"], 0)
        self.assertEqual(acc["cost_usd"], 0.0)
        self.assertEqual(acc["calls"], 1)


class AccumulateTest(unittest.TestCase):
    def test_sums_classes_and_counts_calls(self):
        acc = UM.empty()
        UM.accumulate(acc, UM.parse_usage(_ENVELOPE))
        UM.accumulate(acc, UM.parse_usage(_ENVELOPE))
        self.assertEqual(acc["input_tokens"], 18569 * 2)
        self.assertEqual(acc["cache_read_input_tokens"], 15333 * 2)
        self.assertAlmostEqual(acc["cost_usd"], round(0.1234 * 2, 6))
        self.assertEqual(acc["calls"], 2)
        self.assertEqual(UM.total_tokens(acc), (18569 + 412 + 900 + 15333) * 2)

    def test_first_model_is_pinned_and_failed_call_still_counts(self):
        acc = UM.empty()
        UM.accumulate(acc, UM.parse_usage(_ENVELOPE))            # model set here
        UM.accumulate(acc, UM.parse_usage(""))                   # a failed/empty call: zeros, but counts
        self.assertEqual(acc["model"], "claude-opus-4-8")        # not blanked by the later empty call
        self.assertEqual(acc["calls"], 2)
        self.assertEqual(acc["input_tokens"], 18569)             # empty call added nothing

    def test_empty_is_zeroed_and_independent(self):
        a, b = UM.empty(), UM.empty()
        UM.accumulate(a, UM.parse_usage(_ENVELOPE))
        self.assertEqual(b["calls"], 0)                          # empty() returns a fresh dict each call
        self.assertEqual(UM.total_tokens(b), 0)

    def test_summary_line_is_a_single_line(self):
        acc = UM.empty()
        UM.accumulate(acc, UM.parse_usage(_ENVELOPE))
        line = UM.summary_line(acc)
        self.assertNotIn("\n", line)
        self.assertIn("$0.1234", line)
        self.assertIn("claude-opus-4-8", line)


if __name__ == "__main__":
    unittest.main()
