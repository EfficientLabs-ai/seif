"""unittest for logos/founder_queue_annotate.py — the append-only annotation mechanism for the
founder queue. History must never be rewritten: annotate() only appends; existing bytes never change.
All tests use ONLY temp files — never the real founder_queue.jsonl.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import founder_queue_annotate as FQA  # noqa: E402


ENTRY_1 = {"task_id": "t_ok", "queued_at": "2026-06-28T19:57:53Z", "accepted": True,
           "landed": True, "action": "review+merge (founder gate)"}
ENTRY_2 = {"task_id": "t_other", "queued_at": "2026-06-29T00:00:00Z", "accepted": True,
           "landed": True, "action": "review+merge (founder gate)"}


class FounderQueueAnnotateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-fqa-")
        self.qpath = os.path.join(self.tmp, "queue.jsonl")
        with open(self.qpath, "w") as f:
            f.write(json.dumps(ENTRY_1) + "\n")
            f.write(json.dumps(ENTRY_2) + "\n")
        with open(self.qpath, "rb") as f:
            self._original_bytes = f.read()

    # -- annotate: append-only ---------------------------------------------------
    def test_annotate_appends_exactly_one_line_and_preexisting_bytes_unchanged(self):
        FQA.annotate(self.qpath, {"task_id": "t_ok", "queued_at": ENTRY_1["queued_at"]},
                     "fixture bleed from test suite", kind="fixture")
        with open(self.qpath, "rb") as f:
            new_bytes = f.read()
        self.assertTrue(new_bytes.startswith(self._original_bytes),
                        "every pre-existing byte must remain, byte-identical, as a prefix")
        appended = new_bytes[len(self._original_bytes):]
        lines = [ln for ln in appended.decode().split("\n") if ln]
        self.assertEqual(len(lines), 1, "annotate() must append exactly one line")
        rec = json.loads(lines[0])
        self.assertEqual(rec["type"], "annotation")
        self.assertEqual(rec["kind"], "fixture")
        self.assertEqual(rec["reason"], "fixture bleed from test suite")
        self.assertEqual(rec["match"], {"task_id": "t_ok", "queued_at": ENTRY_1["queued_at"]})
        self.assertIn("ts", rec)

    def test_annotate_zero_match_raises_and_writes_nothing(self):
        with self.assertRaises(ValueError):
            FQA.annotate(self.qpath, {"task_id": "no-such-task"}, "bogus")
        with open(self.qpath, "rb") as f:
            self.assertEqual(f.read(), self._original_bytes, "a failed annotate() must write nothing")

    def test_annotate_zero_match_on_missing_file_raises(self):
        missing = os.path.join(self.tmp, "does-not-exist.jsonl")
        with self.assertRaises(ValueError):
            FQA.annotate(missing, {"task_id": "t_ok"}, "bogus")
        self.assertFalse(os.path.exists(missing))

    def test_annotate_ambiguous_match_raises_and_writes_nothing(self):
        # Codex P2, closed: a retried/re-queued task can legitimately appear twice with the SAME
        # task_id but different queued_at. Matching on --task-id alone must not silently apply one
        # fixture annotation to every entry that shares it.
        retry = {"task_id": "t_ok", "queued_at": "2026-06-29T12:00:00Z", "accepted": True,
                 "landed": True, "action": "review+merge (founder gate)"}
        with open(self.qpath, "a") as f:
            f.write(json.dumps(retry) + "\n")
        with open(self.qpath, "rb") as f:
            before = f.read()
        with self.assertRaises(ValueError):
            FQA.annotate(self.qpath, {"task_id": "t_ok"}, "ambiguous — should be rejected")
        with open(self.qpath, "rb") as f:
            self.assertEqual(f.read(), before, "an ambiguous (rejected) annotate() must write nothing")

    def test_annotate_unambiguous_match_after_narrowing_succeeds(self):
        # The same scenario as above, but narrowed with --queued-at → exactly one match → succeeds,
        # and only THAT entry is annotated (the other same-task_id entry is untouched).
        retry = {"task_id": "t_ok", "queued_at": "2026-06-29T12:00:00Z", "accepted": True,
                 "landed": True, "action": "review+merge (founder gate)"}
        with open(self.qpath, "a") as f:
            f.write(json.dumps(retry) + "\n")
        FQA.annotate(self.qpath, {"task_id": "t_ok", "queued_at": ENTRY_1["queued_at"]}, "narrowed, unambiguous")
        entries = {(e["task_id"], e["queued_at"]): e for e in FQA.read_queue(self.qpath)}
        self.assertEqual(len(entries[("t_ok", ENTRY_1["queued_at"])]["_annotations"]), 1)
        self.assertEqual(entries[("t_ok", retry["queued_at"])]["_annotations"], [],
                          "the OTHER same-task_id entry must be untouched by the narrowed annotation")

    # -- read_queue: attaches annotations, filters fixtures ----------------------
    def test_read_queue_attaches_annotations_to_the_right_entry(self):
        FQA.annotate(self.qpath, {"task_id": "t_ok", "queued_at": ENTRY_1["queued_at"]},
                     "reason A", kind="fixture")
        entries = {e["task_id"]: e for e in FQA.read_queue(self.qpath)}
        self.assertEqual(len(entries["t_ok"]["_annotations"]), 1)
        self.assertEqual(entries["t_ok"]["_annotations"][0]["reason"], "reason A")
        self.assertEqual(entries["t_other"]["_annotations"], [])

    def test_include_annotated_false_filters_fixtures_keeps_unannotated_real_entries(self):
        FQA.annotate(self.qpath, {"task_id": "t_ok", "queued_at": ENTRY_1["queued_at"]},
                     "fixture noise", kind="fixture")
        filtered = FQA.read_queue(self.qpath, include_annotated=False)
        task_ids = [e["task_id"] for e in filtered]
        self.assertNotIn("t_ok", task_ids, "annotated fixture entries must be filtered out")
        self.assertIn("t_other", task_ids, "unannotated real entries must remain")

    def test_include_annotated_false_keeps_non_fixture_annotated_entries(self):
        # a non-"fixture" kind annotation must NOT cause the entry to be filtered
        FQA.annotate(self.qpath, {"task_id": "t_ok", "queued_at": ENTRY_1["queued_at"]},
                     "founder note", kind="note")
        filtered = FQA.read_queue(self.qpath, include_annotated=False)
        self.assertIn("t_ok", [e["task_id"] for e in filtered])

    def test_annotation_records_never_appear_as_queue_entries(self):
        FQA.annotate(self.qpath, {"task_id": "t_ok", "queued_at": ENTRY_1["queued_at"]},
                     "reason A", kind="fixture")
        entries = FQA.read_queue(self.qpath)
        self.assertEqual(len(entries), 2, "only the two real entries, never the annotation record")
        for e in entries:
            self.assertNotEqual(e.get("type"), "annotation")

    def test_read_queue_missing_file_returns_empty_list(self):
        missing = os.path.join(self.tmp, "does-not-exist.jsonl")
        self.assertEqual(FQA.read_queue(missing), [])

    def test_read_queue_skips_malformed_lines(self):
        with open(self.qpath, "a") as f:
            f.write("not json at all\n")
            f.write("42\n")             # valid JSON, not an object
            f.write("\n")               # blank line
        entries = FQA.read_queue(self.qpath)
        self.assertEqual(len(entries), 2, "malformed/non-object lines must be skipped, never fatal")


if __name__ == "__main__":
    unittest.main()
