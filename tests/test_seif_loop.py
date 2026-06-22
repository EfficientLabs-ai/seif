"""unittest for the SEIF loop orchestrator — control logic via an injected fake runner (no LLM/network).

Covers: accepted → queued + reusable lesson; integrity_violation → rejected + recorded + NOT queued;
a throwing runner is contained (one task can't kill the cycle); the accept-rate floor bails early; the
max_tasks cap truncates; trajectory-summary termination mapping; blast-radius is advisory (graph absent
must not crash).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
import seif_loop as SL  # noqa: E402
from tripartite import EpisodicMemory, Memory, WorkingMemory  # noqa: E402


CALLS = []  # records the kwargs the loop forwarded to the runner (cap/forwarding assertions)


def fake_runner(repo, prompt, test_cmd, budget=3, timeout=600, make_pr=True, protected=None):
    """Outcome encoded in the task text — deterministic, no model calls."""
    CALLS.append({"prompt": prompt, "budget": budget, "timeout": timeout,
                  "make_pr": make_pr, "protected": protected})
    if prompt == "ACCEPT":
        return {"accepted": True, "reason": "verified", "landed": True, "pr": "http://pr/1",
                "receipt": {"h": "abc"}, "patch": "diff --git a/src.py b/src.py\n+x"}
    if prompt == "ACCEPT_NOLAND":
        # tests passed (accepted) but the push/PR failed (not landed) → must NOT be queued
        return {"accepted": True, "reason": "verified", "landed": False, "pr": "(push failed rc=1)",
                "receipt": {"h": "abc2"}, "patch": "diff --git a/src.py b/src.py\n+x"}
    if prompt == "INTEGRITY":
        return {"accepted": False, "reason": "integrity_violation", "patch": "",
                "integrity": {"hard": [{"file": "test_x.py"}]}, "receipt": {"h": "def"}}
    if prompt == "BOOM":
        raise RuntimeError("runner blew up")
    return {"accepted": False, "reason": "tests", "patch": "", "receipt": {"h": "ghi"}}


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-loop-")
        self.mem = Memory()
        self.mem.episodic = EpisodicMemory(path=os.path.join(self.tmp, "ep.jsonl"))
        self.mem.working = WorkingMemory(path=os.path.join(self.tmp, "w.json"))
        self.qpath = os.path.join(self.tmp, "queue.jsonl")
        self._orig_q = SL.FOUNDER_QUEUE
        SL.FOUNDER_QUEUE = self.qpath  # resolved at call time inside _queue_for_founder
        CALLS.clear()

    def tearDown(self):
        SL.FOUNDER_QUEUE = self._orig_q

    def _task(self, tid, kind, **kw):
        return {"task_id": tid, "repo": self.tmp, "task": kind, "test_cmd": "x", **kw}

    def test_accept_queues_and_records_lesson(self):
        r = SL.run_loop([self._task("t_ok", "ACCEPT", lesson="resolve paths first")],
                        mem=self.mem, cfg=SL.LoopConfig(max_tasks=10), runner=fake_runner)
        self.assertEqual(r["accepted"], 1)
        self.assertEqual(r["landed"], 1)
        self.assertEqual(r["stopped_reason"], "completed")
        self.assertTrue(os.path.exists(self.qpath), "landed PR must be queued")
        self.assertTrue(self.mem.episodic.reusable_lessons(), "accepted+lesson → reusable episode")

    def test_accepted_but_not_landed_is_not_queued(self):
        # the founder queue gates on LANDED, not accepted — a passed-but-unpushed change must not queue
        r = SL.run_loop([self._task("t_noland", "ACCEPT_NOLAND")],
                        mem=self.mem, cfg=SL.LoopConfig(max_tasks=10), runner=fake_runner)
        self.assertEqual(r["accepted"], 1)
        self.assertEqual(r["landed"], 0)
        self.assertFalse(os.path.exists(self.qpath), "accepted-but-not-landed must NOT be queued")

    def test_caps_forwarded_to_runner(self):
        cfg = SL.LoopConfig(max_tasks=10, budget_per_task=7, timeout=123)
        SL.run_loop([self._task("t1", "FAIL"),
                     self._task("t2", "FAIL", budget=2, protected=("custom/",))],
                    mem=self.mem, cfg=cfg, runner=fake_runner)
        # task 1: no per-task budget/protected → cfg defaults forwarded, protected omitted (runner default None)
        self.assertEqual(CALLS[0]["budget"], 7)
        self.assertEqual(CALLS[0]["timeout"], 123)
        self.assertIsNone(CALLS[0]["protected"])
        # task 2: per-task overrides forwarded
        self.assertEqual(CALLS[1]["budget"], 2)
        self.assertEqual(CALLS[1]["protected"], ("custom/",))

    def test_integrity_violation_rejected_recorded_not_queued(self):
        r = SL.run_loop([self._task("t_bad", "INTEGRITY")],
                        mem=self.mem, cfg=SL.LoopConfig(max_tasks=10), runner=fake_runner)
        self.assertEqual(r["accepted"], 0)
        self.assertEqual(r["landed"], 0)
        self.assertFalse(os.path.exists(self.qpath), "non-landed must NOT be queued")
        rec = self.mem.episodic.query(task_id="t_bad")[0]["summary"]
        self.assertEqual(rec["termination_reason"], "rejected")
        self.assertTrue(rec["prohibited_reuse_reasons"])

    def test_throwing_runner_contained(self):
        r = SL.run_loop([self._task("t_boom", "BOOM"), self._task("t_ok2", "ACCEPT")],
                        mem=self.mem, cfg=SL.LoopConfig(max_tasks=10), runner=fake_runner)
        self.assertEqual(r["attempted"], 2)   # the throw did not kill the cycle
        self.assertEqual(r["accepted"], 1)
        boom = self.mem.episodic.query(task_id="t_boom")[0]["summary"]
        self.assertEqual(boom["termination_reason"], "error")

    def test_accept_rate_floor_bails_early(self):
        backlog = [self._task(f"f{i}", "FAIL") for i in range(8)]
        cfg = SL.LoopConfig(max_tasks=8, min_accept_rate=0.5, floor_after=3)
        r = SL.run_loop(backlog, mem=self.mem, cfg=cfg, runner=fake_runner)
        self.assertEqual(r["attempted"], 3)
        self.assertIn("accept_rate_floor", r["stopped_reason"])
        self.assertEqual(r["skipped"], 5)

    def test_floor_not_enforced_before_floor_after(self):
        # all failing, floor_after=4: the loop must run tasks 1-3 WITHOUT bailing, then fire exactly at 4
        backlog = [self._task(f"f{i}", "FAIL") for i in range(8)]
        cfg = SL.LoopConfig(max_tasks=8, min_accept_rate=0.5, floor_after=4)
        r = SL.run_loop(backlog, mem=self.mem, cfg=cfg, runner=fake_runner)
        self.assertEqual(r["attempted"], 4, "did not bail before floor_after, fired exactly at it")
        self.assertIn("accept_rate_floor", r["stopped_reason"])

    def test_rate_at_or_above_threshold_completes(self):
        # rate stays >= 50% at every checkpoint past floor_after → no early bail, full backlog runs
        backlog = [self._task("a1", "ACCEPT"), self._task("f1", "FAIL"), self._task("a2", "ACCEPT"),
                   self._task("f2", "FAIL"), self._task("a3", "ACCEPT")]
        cfg = SL.LoopConfig(max_tasks=8, min_accept_rate=0.5, floor_after=3)
        r = SL.run_loop(backlog, mem=self.mem, cfg=cfg, runner=fake_runner)
        self.assertEqual(r["attempted"], 5)
        self.assertEqual(r["stopped_reason"], "completed")

    def test_max_tasks_cap_truncates(self):
        backlog = [self._task(f"f{i}", "FAIL") for i in range(8)]
        r = SL.run_loop(backlog, mem=self.mem, cfg=SL.LoopConfig(max_tasks=2), runner=fake_runner)
        self.assertEqual(r["attempted"], 2)
        self.assertEqual(r["skipped"], 6)

    def test_blast_radius_advisory_no_graph(self):
        # repo has no graphify-out → blast radius must report graph absent, not raise
        b = SL._blast_radius(self.mem, self.tmp, "diff --git a/x.py b/x.py\n+y")
        self.assertIn("changed", b)
        self.assertIsNone(b["impacted"])


if __name__ == "__main__":
    unittest.main()
