"""unittest for logos/episodic_export — the episode-JSONL → flat training table (CSV + JSONL) exporter.

Covers: the STABLE documented column schema (order is the contract); flatten() pulls nested training
fields (model_requested/actual, attempt_number, fresh vs cache-read tokens, cost_usd, evidence_result,
final_outcome, receipt_hash, ts, task_id) to top-level scalars; CSV header + JSONL keys are exactly
COLUMNS; torn/non-JSON lines are skipped; an empty/absent input still writes a header-only CSV (never
crashes); and an END-TO-END pass where the SEIF loop records an episode and the exporter reads it back
(the loop and the exporter agree on the on-disk schema — the whole point of the feature).
"""
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
import episodic_export as EX  # noqa: E402
import seif_loop as SL  # noqa: E402
import trajectory_summary as TS  # noqa: E402
from tripartite import EpisodicMemory, Memory, WorkingMemory  # noqa: E402


def _episode(ts, summary):
    return {"ts": ts, "summary": summary}


def _full_summary(task_id, *, term="accepted", model_req="claude-opus-4-8", model_act="claude-opus-4-8",
                  calls=2, fresh=1500, cache=9000, cost=0.0123, evidence="pass", receipt="abc123",
                  lesson="resolve paths first", prohibited=None):
    return {
        "attempt_id": f"{task_id}#0", "task_id": task_id, "hypothesis": "h",
        "termination_reason": term, "reusable_lesson_candidate": lesson,
        "prohibited_reuse_reasons": prohibited or [],
        "cost": {"model_requested": model_req, "model_actual": model_act, "attempt_number": calls,
                 "fresh_in": fresh, "cache_read": cache, "cost_usd": cost,
                 "evidence_result": evidence, "receipt_hash": receipt},
    }


class SchemaTest(unittest.TestCase):
    def test_columns_contain_required_training_fields(self):
        # the task spec's required signal must each map to a documented column
        for required in ("ts", "task_id", "model_requested", "model_actual", "attempt_number",
                         "fresh_in_tokens", "cache_read_tokens", "cost_usd", "evidence_result",
                         "final_outcome", "receipt_hash"):
            self.assertIn(required, EX.COLUMNS, required)

    def test_columns_is_a_tuple_stable_order(self):
        # the schema is a fixed tuple (order is the contract); ts is first, reusable is last
        self.assertIsInstance(EX.COLUMNS, tuple)
        self.assertEqual(EX.COLUMNS[0], "ts")
        self.assertEqual(EX.COLUMNS[-1], "reusable")


class FlattenTest(unittest.TestCase):
    def test_flatten_pulls_nested_training_fields(self):
        rec = _episode("2026-06-24T00:00:00Z", _full_summary("t1"))
        r = EX.flatten(rec)
        self.assertEqual(r["ts"], "2026-06-24T00:00:00Z")
        self.assertEqual(r["task_id"], "t1")
        self.assertEqual(r["attempt_id"], "t1#0")
        self.assertEqual(r["model_requested"], "claude-opus-4-8")
        self.assertEqual(r["model_actual"], "claude-opus-4-8")
        self.assertEqual(r["attempt_number"], 2)
        self.assertEqual(r["fresh_in_tokens"], 1500)
        self.assertEqual(r["cache_read_tokens"], 9000)
        self.assertAlmostEqual(r["cost_usd"], 0.0123)
        self.assertEqual(r["evidence_result"], "pass")
        self.assertEqual(r["final_outcome"], "accepted")    # = termination_reason
        self.assertEqual(r["receipt_hash"], "abc123")
        self.assertTrue(r["reusable"])

    def test_flatten_typed_defaults_on_missing(self):
        # a summary with no cost dict + missing fields → typed empties, never KeyError
        r = EX.flatten(_episode("", {"task_id": "x", "termination_reason": "stuck"}))
        self.assertEqual(r["model_actual"], "")
        self.assertEqual(r["attempt_number"], 0)
        self.assertEqual(r["fresh_in_tokens"], 0)
        self.assertEqual(r["cache_read_tokens"], 0)
        self.assertEqual(r["cost_usd"], 0.0)
        self.assertEqual(r["receipt_hash"], "")
        self.assertEqual(r["final_outcome"], "stuck")
        self.assertFalse(r["reusable"])

    def test_flatten_none_model_requested_becomes_empty_string(self):
        rec = _episode("t", _full_summary("t", model_req=None))
        self.assertEqual(EX.flatten(rec)["model_requested"], "")

    def test_flatten_non_dict_record_is_safe(self):
        for bad in ("nope", None, 7, [], {"summary": "not a dict"}):
            r = EX.flatten(bad)
            self.assertEqual(r["task_id"], "")
            self.assertEqual(r["fresh_in_tokens"], 0)
            self.assertFalse(r["reusable"])

    def test_flatten_non_numeric_cost_fields_degrade_not_crash(self):
        # a historical/corrupt episode whose token/cost fields hold non-numeric junk must export as 0,
        # not raise out of flatten() (the 'instrumentation never crashes' contract on the read side too).
        rec = _episode("t", {"task_id": "t", "termination_reason": "accepted",
                             "cost": {"attempt_number": "two", "fresh_in": None, "cache_read": [1, 2],
                                      "cost_usd": "free", "model_actual": 1234, "receipt_hash": None}})
        r = EX.flatten(rec)  # must not raise
        self.assertEqual(r["attempt_number"], 0)
        self.assertEqual(r["fresh_in_tokens"], 0)
        self.assertEqual(r["cache_read_tokens"], 0)
        self.assertEqual(r["cost_usd"], 0.0)
        self.assertEqual(r["receipt_hash"], "")

    def test_flatten_cost_not_a_dict_degrades(self):
        # `cost` present but not a dict (e.g. a legacy string) → treated as empty, typed zeros, no crash
        rec = _episode("t", {"task_id": "t", "termination_reason": "stuck", "cost": "n/a"})
        r = EX.flatten(rec)
        self.assertEqual(r["fresh_in_tokens"], 0)
        self.assertEqual(r["cost_usd"], 0.0)
        self.assertEqual(r["final_outcome"], "stuck")

    def test_reusable_filter_matches_trajectory_summary(self):
        # accepted + lesson + no prohibition → reusable; a prohibition flips it false
        ok = _full_summary("t", term="accepted", lesson="x", prohibited=[])
        bad = _full_summary("t", term="accepted", lesson="x", prohibited=["overfit"])
        rejected = _full_summary("t", term="rejected", lesson="x")
        self.assertTrue(EX.flatten(_episode("t", ok))["reusable"])
        self.assertFalse(EX.flatten(_episode("t", bad))["reusable"])
        self.assertFalse(EX.flatten(_episode("t", rejected))["reusable"])
        # parity with the canonical filter (build a valid summary so TS.is_reusable can judge it)
        canon = TS.build_summary("a#0", "t", "h", "accepted", reusable_lesson_candidate="x")
        self.assertEqual(EX.flatten(_episode("t", canon))["reusable"], TS.is_reusable(canon))


class ExportIOTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-export-")
        self.ep = os.path.join(self.tmp, "episodes.jsonl")
        with open(self.ep, "w") as f:
            f.write(json.dumps(_episode("2026-06-24T00:00:00Z", _full_summary("t1"))) + "\n")
            f.write(json.dumps(_episode("2026-06-24T00:01:00Z",
                    _full_summary("t2", term="rejected", evidence="fail", lesson="",
                                  prohibited=["overfit"], model_req=None))) + "\n")
            f.write('{"ts":"x","summary":{"torn"\n')  # torn JSON line — must be skipped

    def test_export_writes_both_files_and_counts_rows(self):
        out = EX.export(self.ep, os.path.join(self.tmp, "train"))
        self.assertEqual(out["rows"], 2)  # torn line skipped
        self.assertTrue(os.path.exists(out["csv"]))
        self.assertTrue(os.path.exists(out["jsonl"]))

    def test_csv_header_is_columns_in_order(self):
        out = EX.export(self.ep, os.path.join(self.tmp, "train"))
        with open(out["csv"]) as f:
            header = next(csv.reader(f))
        self.assertEqual(tuple(header), EX.COLUMNS)

    def test_csv_body_round_trips_values(self):
        out = EX.export(self.ep, os.path.join(self.tmp, "train"))
        with open(out["csv"]) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["task_id"], "t1")
        self.assertEqual(rows[0]["fresh_in_tokens"], "1500")
        self.assertEqual(rows[0]["evidence_result"], "pass")
        self.assertEqual(rows[1]["evidence_result"], "fail")
        self.assertEqual(rows[1]["model_requested"], "")  # None → empty string

    def test_jsonl_keys_are_columns(self):
        out = EX.export(self.ep, os.path.join(self.tmp, "train"))
        with open(out["jsonl"]) as f:
            objs = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(objs), 2)
        self.assertEqual(list(objs[0].keys()), list(EX.COLUMNS))
        self.assertEqual(objs[0]["fresh_in_tokens"], 1500)
        self.assertIs(objs[0]["reusable"], True)
        self.assertIs(objs[1]["reusable"], False)

    def test_empty_input_writes_header_only_csv(self):
        out = EX.export(os.path.join(self.tmp, "absent.jsonl"), os.path.join(self.tmp, "empty"))
        self.assertEqual(out["rows"], 0)
        with open(out["csv"]) as f:
            reader = csv.reader(f)
            self.assertEqual(next(reader), list(EX.COLUMNS))
            self.assertEqual(list(reader), [])  # header only
        with open(out["jsonl"]) as f:
            self.assertEqual(f.read(), "")  # empty JSONL

    def test_read_episodes_skips_torn_and_missing(self):
        # the torn line is skipped; an absent file yields nothing
        self.assertEqual(len(list(EX.read_episodes(self.ep))), 2)
        self.assertEqual(list(EX.read_episodes(os.path.join(self.tmp, "nope.jsonl"))), [])


class EndToEndLoopExportTest(unittest.TestCase):
    """The loop records an episode; the exporter reads it back. Proves loop ⇄ export agree on the schema."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-e2e-")
        self.mem = Memory()
        self.mem.episodic = EpisodicMemory(path=os.path.join(self.tmp, "ep.jsonl"))
        self.mem.working = WorkingMemory(path=os.path.join(self.tmp, "w.json"))
        self._orig_q = SL.FOUNDER_QUEUE
        SL.FOUNDER_QUEUE = os.path.join(self.tmp, "queue.jsonl")

    def tearDown(self):
        SL.FOUNDER_QUEUE = self._orig_q

    def _runner(self, repo, prompt, test_cmd, **kw):
        # a measured ACCEPT: carries usage (usage_meter spend shape) + model fields + a receipt
        if prompt == "ACCEPT":
            return {"accepted": True, "reason": "verified", "landed": True, "pr": "http://pr/1",
                    "receipt": {"h": "rh_accept"}, "patch": "diff --git a/src.py b/src.py\n+x",
                    "model_requested": "claude-opus-4-8", "model_actual": "claude-opus-4-8",
                    "usage": {"calls": 2, "input_tokens": 1200, "output_tokens": 300,
                              "cache_read_input_tokens": 8000, "cache_creation_input_tokens": 100,
                              "cost_usd": 0.0321, "model": "claude-opus-4-8"}}
        # a measured FAIL: tests didn't pass; usage still recorded
        return {"accepted": False, "reason": "tests", "patch": "", "receipt": {"h": "rh_fail"},
                "model_requested": "claude-opus-4-8", "model_actual": "claude-sonnet-4-5",
                "usage": {"calls": 3, "input_tokens": 900, "output_tokens": 200,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                          "cost_usd": 0.0095, "model": "claude-sonnet-4-5"}}

    def test_loop_records_one_episode_per_task_with_training_fields(self):
        SL.run_loop([{"task_id": "e_ok", "repo": self.tmp, "task": "ACCEPT", "test_cmd": "x",
                      "lesson": "scope the fix"},
                     {"task_id": "e_no", "repo": self.tmp, "task": "FAIL", "test_cmd": "x"}],
                    mem=self.mem, cfg=SL.LoopConfig(max_tasks=10), runner=self._runner)
        # exactly one episode per task
        self.assertEqual(len(self.mem.episodic.query()), 2)
        # the recorded cost dict carries the training signal (loop side)
        ok = self.mem.episodic.query(task_id="e_ok")[0]["summary"]
        self.assertEqual(ok["cost"]["model_requested"], "claude-opus-4-8")
        self.assertEqual(ok["cost"]["model_actual"], "claude-opus-4-8")
        self.assertEqual(ok["cost"]["attempt_number"], 2)
        self.assertEqual(ok["cost"]["fresh_in"], 1200)
        self.assertEqual(ok["cost"]["cache_read"], 8000)
        self.assertAlmostEqual(ok["cost"]["cost_usd"], 0.0321)
        self.assertEqual(ok["cost"]["evidence_result"], "pass")
        self.assertEqual(ok["cost"]["receipt_hash"], "rh_accept")
        # CBOM: the failing task shows a model downgrade (requested opus, served sonnet)
        no = self.mem.episodic.query(task_id="e_no")[0]["summary"]
        self.assertEqual(no["cost"]["model_actual"], "claude-sonnet-4-5")
        self.assertEqual(no["cost"]["evidence_result"], "fail")

    def test_export_of_loop_recorded_episodes(self):
        SL.run_loop([{"task_id": "e_ok", "repo": self.tmp, "task": "ACCEPT", "test_cmd": "x",
                      "lesson": "scope the fix"},
                     {"task_id": "e_no", "repo": self.tmp, "task": "FAIL", "test_cmd": "x"}],
                    mem=self.mem, cfg=SL.LoopConfig(max_tasks=10), runner=self._runner)
        out = EX.export(self.mem.episodic.path, os.path.join(self.tmp, "train"))
        self.assertEqual(out["rows"], 2)
        rows = {r["task_id"]: r for r in EX.build_rows(self.mem.episodic.path)}
        ok = rows["e_ok"]
        self.assertEqual(ok["model_actual"], "claude-opus-4-8")
        self.assertEqual(ok["fresh_in_tokens"], 1200)
        self.assertEqual(ok["cache_read_tokens"], 8000)
        self.assertEqual(ok["attempt_number"], 2)
        self.assertEqual(ok["evidence_result"], "pass")
        self.assertEqual(ok["final_outcome"], "accepted")
        self.assertEqual(ok["receipt_hash"], "rh_accept")
        self.assertTrue(ok["reusable"])              # accepted + lesson + no prohibition
        self.assertTrue(ok["ts"])                    # the record envelope ts survived to the table
        no = rows["e_no"]
        self.assertEqual(no["evidence_result"], "fail")
        self.assertEqual(no["final_outcome"], "rejected")
        self.assertFalse(no["reusable"])


if __name__ == "__main__":
    unittest.main()
