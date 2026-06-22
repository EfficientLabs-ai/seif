"""unittest for Tripartite Memory v1 (L1 working / L2 episodic / L3 semantic + facade).

The module ships an inline --selftest; this is the CI-runnable equivalent with finer granularity and
explicit coverage of the graceful-degradation contract (Redis-absent → file; missing/corrupt graph or
store → degrade, never crash) that the whole 'runs with whatever infra exists' premise depends on.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import trajectory_summary as TS  # noqa: E402
from tripartite import EpisodicMemory, Memory, SemanticMemory, WorkingMemory  # noqa: E402


def _graph(tmp, name="repo"):
    repo = os.path.join(tmp, name)
    os.makedirs(os.path.join(repo, "graphify-out"))
    g = {"directed": False,
         "nodes": [{"id": "core", "source_file": "src/core.py", "label": "core.py"},
                   {"id": "mid", "source_file": "src/mid.py", "label": "mid.py"},
                   {"id": "app", "source_file": "src/app.py", "label": "app.py"},
                   {"id": "loner", "source_file": "src/loner.py", "label": "loner.py"}],
         "links": [{"source": "mid", "target": "core", "relation": "imports_from"},
                   {"source": "app", "target": "mid", "relation": "imports_from"}],
         "built_at_commit": "deadbeef"}
    json.dump(g, open(os.path.join(repo, "graphify-out", "graph.json"), "w"))
    return repo


class TestL1Working(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-l1-")
        self.wm = WorkingMemory(path=os.path.join(self.tmp, "w.json"))

    def test_file_backend_no_redis(self):
        self.assertEqual(self.wm.backend, "file")

    def test_set_get_delete(self):
        self.wm.set("k", {"a": 1})
        self.assertEqual(self.wm.get("k"), {"a": 1})
        self.wm.delete("k")
        self.assertIsNone(self.wm.get("k"))

    def test_default_on_missing(self):
        self.assertEqual(self.wm.get("nope", 42), 42)

    def test_ttl_expiry_enforced_on_read(self):
        self.wm.set("e", 1, ttl=-1)  # already expired
        self.assertEqual(self.wm.get("e", "gone"), "gone")

    def test_keys_prefix_and_strip(self):
        self.wm.set("a", 1); self.wm.set("ab", 2); self.wm.set("zz", 3)
        self.assertEqual(self.wm.keys("a"), ["a", "ab"])

    def test_namespace_isolation_same_file(self):
        shared = os.path.join(self.tmp, "shared.json")
        a = WorkingMemory(path=shared, namespace="ns_a")
        b = WorkingMemory(path=shared, namespace="ns_b")
        a.set("k", "from_a"); b.set("k", "from_b")
        self.assertEqual(a.get("k"), "from_a")
        self.assertEqual(b.get("k"), "from_b")
        self.assertEqual(a.keys(), ["k"])  # keys() strips the namespace

    def test_corrupt_store_quarantined_not_silent(self):
        p = os.path.join(self.tmp, "corrupt.json")
        open(p, "w").write("{garbage")
        wm = WorkingMemory(path=p)
        self.assertIsNone(wm.get("anything"))  # handled, fresh start
        self.assertTrue(any(f.startswith("corrupt.json.corrupt-") for f in os.listdir(self.tmp)))


class TestL2Episodic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-l2-")
        self.em = EpisodicMemory(path=os.path.join(self.tmp, "ep.jsonl"))
        self.ok = TS.build_summary("a1", "task_x", "fix cache key", "accepted",
                                   files_changed=["a.py"], evidence_passed=["L2"],
                                   reusable_lesson_candidate="resolve paths first")
        self.bad = TS.build_summary("a2", "task_x", "narrow fix", "rejected",
                                    evidence_failed=["L2"], prohibited_reuse_reasons=["overfit"])
        self.em.record(self.ok); self.em.record(self.bad)

    def test_query_by_task_and_termination(self):
        self.assertEqual(len(self.em.query(task_id="task_x")), 2)
        self.assertEqual(len(self.em.query(termination="accepted")), 1)

    def test_recent_is_newest_first(self):
        self.assertEqual(self.em.recent(1)[0]["summary"]["attempt_id"], "a2")

    def test_reusable_filter(self):
        lessons = self.em.reusable_lessons()
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["summary"]["attempt_id"], "a1")

    def test_malformed_summary_rejected(self):
        with self.assertRaises(TS.SummaryError):
            self.em.record({"not": "a valid summary"})

    def test_torn_final_line_tolerated(self):
        with open(self.em.path, "a") as f:
            f.write('{"ts":"x","summary":{"incomplete"')  # torn line
        self.assertEqual(len(self.em.query(task_id="task_x")), 2)  # ignored, no crash

    def test_query_missing_file_empty(self):
        em = EpisodicMemory(path=os.path.join(self.tmp, "absent.jsonl"))
        self.assertEqual(em.query(), [])


class TestL3Semantic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-l3-")
        self.sm = SemanticMemory(_graph(self.tmp))

    def test_available(self):
        self.assertTrue(self.sm.available)

    def test_impact_transitive(self):
        self.assertEqual(self.sm.impact("src/core.py"), ["src/app.py", "src/mid.py"])

    def test_impact_depth_limited(self):
        self.assertEqual(self.sm.impact("src/core.py", depth=1), ["src/mid.py"])

    def test_dependencies(self):
        self.assertEqual(self.sm.dependencies("src/app.py"), ["src/core.py", "src/mid.py"])

    def test_isolated_node(self):
        self.assertEqual(self.sm.impact("src/loner.py"), [])
        self.assertEqual(self.sm.dependencies("src/loner.py"), [])

    def test_path_basename_resolution(self):
        self.assertEqual(self.sm.path("app.py", "core.py"), ["app", "mid", "core"])

    def test_built_at_commit(self):
        self.assertEqual(self.sm.built_at_commit, "deadbeef")

    def test_missing_graphify_out_degrades(self):
        empty = os.path.join(self.tmp, "empty_repo")
        os.makedirs(empty)
        sm = SemanticMemory(empty)
        self.assertFalse(sm.available)
        self.assertEqual(sm.impact("x.py"), [])
        self.assertEqual(sm.dependencies("x.py"), [])
        self.assertEqual(sm.neighbors("x"), [])
        self.assertEqual(sm.path("a", "b"), [])
        self.assertIsNone(sm.built_at_commit)
        self.assertTrue(sm.is_stale())

    def test_corrupt_graph_degrades_not_crash(self):
        bad = os.path.join(self.tmp, "bad_repo")
        os.makedirs(os.path.join(bad, "graphify-out"))
        open(os.path.join(bad, "graphify-out", "graph.json"), "w").write("{not json")
        sm = SemanticMemory(bad)
        self.assertTrue(sm.available)        # file exists pre-load
        self.assertEqual(sm.impact("x.py"), [])
        self.assertFalse(sm.available)       # flipped after the failed load

    def test_query_unavailable_graph_returns_fallback_marker(self):
        # a repo WITHOUT graphify-out → query() must hit the early fallback (no CLI/model call) and say so,
        # not raise. (Using an unavailable graph also keeps this test from invoking the real graphify CLI.)
        empty = os.path.join(self.tmp, "noq_repo")
        os.makedirs(empty)
        out = SemanticMemory(empty).query("anything")
        self.assertIn("[semantic]", out)
        self.assertIn("no graphify query available", out)


class TestFacade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-fac-")
        self.mem = Memory(ecp_ledger=os.path.join(self.tmp, "nope.json"))
        self.mem.working = WorkingMemory(path=os.path.join(self.tmp, "w.json"))
        self.mem.episodic = EpisodicMemory(path=os.path.join(self.tmp, "ep.jsonl"))

    def test_remember_recall(self):
        self.mem.remember("cur", {"step": 3})
        self.assertEqual(self.mem.recall("cur"), {"step": 3})

    def test_graph_cached_per_repo(self):
        repo = _graph(self.tmp)
        g1 = self.mem.graph(repo)
        g2 = self.mem.graph(repo)
        self.assertIs(g1, g2)

    def test_continuity_snapshot(self):
        s = TS.build_summary("a1", "tk", "h", "accepted", reusable_lesson_candidate="x")
        self.mem.record_attempt(s)
        snap = self.mem.continuity_snapshot(task_id="tk", n_episodes=3)
        self.assertEqual(snap["l1_backend"], "file")
        self.assertFalse(snap["ecp_ledger_present"])     # missing ledger handled
        self.assertEqual(len(snap["recent_episodes"]), 1)
        self.assertEqual(len(snap["reusable_lessons"]), 1)


if __name__ == "__main__":
    unittest.main()
