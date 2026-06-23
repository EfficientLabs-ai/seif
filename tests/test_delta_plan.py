"""unittest for the checkpoint-aware delta-planning CONTEXT (logos/delta_plan.py).

delta_context() is PURE composition over the existing primitives — L4 checkpoint (base), L3 semantic
graph (blast_radius), L2 episodic memory (prior_lessons / prior_failures). These tests prove it returns
the right composed values AND that it degrades to None/[] when checkpoint, graph, or episodes are absent
(the whole point: a planner can always call it without a crash).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import checkpoint as CP  # noqa: E402
import delta_plan  # noqa: E402
import tripartite  # noqa: E402
import trajectory_summary as TS  # noqa: E402
from tripartite import EpisodicMemory  # noqa: E402


def _graph(repo):
    """Synthetic graphify-out: app -> mid -> core (imports), plus an unconnected loner."""
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


class DeltaContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-delta-")
        # Pin the L4 ledger and the L2 store to temp paths so the test is hermetic.
        self._cp_ledger, self._cp_failures = CP.LEDGER, CP.FAILURES
        self._store = tripartite.STORE
        CP.LEDGER = os.path.join(self.tmp, "cp.jsonl")
        CP.FAILURES = os.path.join(self.tmp, "fail.jsonl")
        tripartite.STORE = os.path.join(self.tmp, "store")   # EpisodicMemory() default reads from here
        # A real git repo with one commit (CP.create requires a git-sha commit).
        self.repo = os.path.join(self.tmp, "repo")
        g = lambda *a: subprocess.run(  # noqa: E731
            ["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
            check=True, capture_output=True)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
        g("add", "-A"); g("commit", "-qm", "v1")
        self.commit = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()

    def tearDown(self):
        CP.LEDGER, CP.FAILURES = self._cp_ledger, self._cp_failures
        tripartite.STORE = self._store
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _record_episodes(self):
        em = EpisodicMemory()   # default path now under tripartite.STORE (temp)
        em.record(TS.build_summary("att1", "task_x", "fix cache key", "accepted",
                                   files_changed=["src/core.py"], evidence_passed=["L2"],
                                   reusable_lesson_candidate="resolve paths before keying"))
        em.record(TS.build_summary("att2", "task_x", "narrow fix", "rejected",
                                   evidence_failed=["L2"], prohibited_reuse_reasons=["overfit"]))
        # an episode for a DIFFERENT task — must not leak into task_x context
        em.record(TS.build_summary("att3", "task_y", "unrelated", "rejected", evidence_failed=["L9"]))

    # ---- full composition: base + blast_radius + lessons + failures ----
    def test_composes_all_fields(self):
        _graph(self.repo)
        cp = CP.create(self.repo, "add works", commit=self.commit,
                       proof={"outcome": "pass", "receipt": "r1", "exit_code": 0},
                       context={"task": "impl add", "files_changed": ["calc.py"]})
        self._record_episodes()

        ctx = delta_plan.delta_context(self.repo, changed_files=["src/core.py"], task_id="task_x")

        # base = the last healthy checkpoint
        self.assertIsNotNone(ctx["base"])
        self.assertEqual(ctx["base"]["id"], cp["id"])
        # blast_radius = reverse-import closure of src/core.py (mid imports it, app transitively)
        self.assertEqual(ctx["blast_radius"], ["src/app.py", "src/mid.py"])
        # prior_lessons = the accepted+lesson episode for task_x only
        self.assertEqual(len(ctx["prior_lessons"]), 1)
        self.assertEqual(ctx["prior_lessons"][0]["summary"]["attempt_id"], "att1")
        # prior_failures = the rejected episode for task_x only (not task_y)
        self.assertEqual([r["summary"]["attempt_id"] for r in ctx["prior_failures"]], ["att2"])
        # the whole thing is a plain JSON-serializable dict
        self.assertEqual(sorted(ctx), ["base", "blast_radius", "prior_failures", "prior_lessons"])
        json.dumps(ctx)

    # ---- blast_radius respects the union over multiple changed files ----
    def test_blast_radius_unions_changed_files(self):
        _graph(self.repo)
        ctx = delta_plan.delta_context(self.repo, changed_files=["src/core.py", "src/mid.py"])
        # core's dependents {mid, app} ∪ mid's dependents {app} = {app, mid}, sorted
        self.assertEqual(ctx["blast_radius"], ["src/app.py", "src/mid.py"])

    # ---- graceful degradation: nothing present → None / [] but never a crash ----
    def test_degrades_when_everything_absent(self):
        # no graphify-out, no checkpoints, no episodes (fresh temp ledger + store)
        ctx = delta_plan.delta_context(self.repo, changed_files=["src/core.py"], task_id="task_x")
        self.assertIsNone(ctx["base"])           # no healthy checkpoint
        self.assertIsNone(ctx["blast_radius"])   # no graph to answer from
        self.assertEqual(ctx["prior_lessons"], [])
        self.assertEqual(ctx["prior_failures"], [])

    def test_blast_radius_none_without_graph_even_with_checkpoint(self):
        CP.create(self.repo, "x", commit=self.commit, proof={"outcome": "pass", "receipt": "r1"})
        ctx = delta_plan.delta_context(self.repo, changed_files=["src/core.py"])
        self.assertIsNotNone(ctx["base"])        # checkpoint present
        self.assertIsNone(ctx["blast_radius"])   # but no graph → cannot know

    def test_no_args_safe(self):
        ctx = delta_plan.delta_context(self.repo)
        self.assertIsNone(ctx["base"])
        self.assertIsNone(ctx["blast_radius"])
        self.assertEqual(ctx["prior_lessons"], [])
        self.assertEqual(ctx["prior_failures"], [])

    def test_task_id_none_does_not_pull_global_episodes(self):
        # episodes for task_x AND task_y exist; an UNSCOPED call (task_id=None) must NOT pull any of them
        self._record_episodes()
        ctx = delta_plan.delta_context(self.repo, changed_files=["src/core.py"], task_id=None)
        self.assertEqual(ctx["prior_lessons"], [], "unscoped call must not surface global lessons")
        self.assertEqual(ctx["prior_failures"], [], "unscoped call must not surface global failures")

    def test_corrupt_graph_blast_radius_is_none(self):
        # graphify-out/graph.json EXISTS but is corrupt → cannot know the blast radius → None, not []
        os.makedirs(os.path.join(self.repo, "graphify-out"))
        open(os.path.join(self.repo, "graphify-out", "graph.json"), "w").write("{ not json")
        ctx = delta_plan.delta_context(self.repo, changed_files=["src/core.py"], task_id="task_x")
        self.assertIsNone(ctx["blast_radius"], "corrupt graph must yield None (unknown), not [] (nothing)")


if __name__ == "__main__":
    unittest.main()
