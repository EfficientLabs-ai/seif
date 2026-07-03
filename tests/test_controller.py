"""unittest for the SEIF two-plane controller (logos/controller.py).

The controller is the persistent plane; a worker is one `seif_run.seif_run()` call inside a route-compiled
lean environment. These tests exercise the control plane end-to-end with an INJECTED fake worker (no LLM,
no network): dispatch, cap enforcement, the accept-rate floor, and the founder queue — all REUSED from
seif_loop. We also assert the new wiring the controller actually adds: route-table loading, route
matching/compilation, and that the worker adapter forwards `route=` to a real-shaped worker while leaving
a route-unaware fake untouched.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
import controller as C  # noqa: E402
import ecp_route as ECP  # noqa: E402
import seif_loop as SL  # noqa: E402
from tripartite import EpisodicMemory, Memory, WorkingMemory  # noqa: E402


# A route-aware fake worker: records every call (incl. the injected route + caps) and returns a scripted
# outcome keyed by the task prompt. No model, no network. Accepts **kw so route injection drives it.
CALLS = []


def fake_worker(repo, prompt, test_cmd, budget=3, timeout=600, make_pr=True, protected=None, route=None):
    CALLS.append({"repo": repo, "prompt": prompt, "budget": budget, "timeout": timeout,
                  "make_pr": make_pr, "protected": protected, "route": route})
    if "ACCEPT" in prompt:
        return {"accepted": True, "reason": "verified", "landed": True, "pr": "http://pr/1",
                "receipt": {"h": "abc"}, "patch": "diff --git a/src.py b/src.py\n+x"}
    if "NOLAND" in prompt:
        return {"accepted": True, "reason": "verified", "landed": False, "pr": "(push failed)",
                "receipt": {"h": "abc2"}, "patch": "diff --git a/src.py b/src.py\n+x"}
    if "INTEGRITY" in prompt:
        return {"accepted": False, "reason": "integrity_violation", "patch": "",
                "integrity": {"hard": [{"file": "test_x.py"}]}, "receipt": {"h": "def"}}
    if "BOOM" in prompt:
        raise RuntimeError("worker blew up")
    return {"accepted": False, "reason": "tests", "patch": "", "receipt": {"h": "ghi"}}


SAMPLE_ROUTE = {
    "schema": ECP.SCHEMA,
    "id": "test-fix-route",
    "match": {"intents": ["fix", "debug", "modify"], "paths": ["logos/**/*.py"]},
    "tools": {"allow": ["Read", "Edit"], "deny": ["Bash(git push *)"], "mcp": []},
    "budget": {"requested_model": "claude-haiku", "max_turns": 3},
    "verification": {"commands": ["python3 -m unittest"]},
}


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-ctrl-")
        self.mem = Memory()
        self.mem.episodic = EpisodicMemory(path=os.path.join(self.tmp, "ep.jsonl"))
        self.mem.working = WorkingMemory(path=os.path.join(self.tmp, "w.json"))
        self.qpath = os.path.join(self.tmp, "queue.jsonl")
        CALLS.clear()

    def _task(self, tid, kind, **kw):
        return {"task_id": tid, "repo": self.tmp, "task": kind, "test_cmd": "x", **kw}

    def _ctrl(self, backlog, routes=None, cfg=None, runner=None):
        return C.Controller(backlog, routes=routes if routes is not None else [SAMPLE_ROUTE],
                            mem=self.mem, cfg=cfg or SL.LoopConfig(max_tasks=10),
                            runner=runner or fake_worker, queue_path=self.qpath)

    # -- dispatch --------------------------------------------------------------
    def test_dispatch_one_task_runs_through_gate(self):
        ctrl = self._ctrl([])
        rec = ctrl.dispatch(self._task("t_ok", "ACCEPT"))
        self.assertTrue(rec["accepted"])
        self.assertTrue(rec["landed"])
        self.assertEqual(rec["task_id"], "t_ok")
        self.assertEqual(len(CALLS), 1, "exactly one worker launched per dispatch")

    def test_dispatch_redirects_founder_queue_to_controller_queue_path(self):
        # dispatch() must apply the same save/redirect/restore pattern run() uses — a Controller
        # constructed with queue_path= must never append to SL.FOUNDER_QUEUE's default when used via
        # dispatch() directly (this is exactly how leaked fixture lines reached the production queue).
        sentinel = os.path.join(self.tmp, "sentinel-default-queue.jsonl")
        orig_default = SL.FOUNDER_QUEUE
        SL.FOUNDER_QUEUE = sentinel
        try:
            ctrl = self._ctrl([])
            rec = ctrl.dispatch(self._task("t_ok", "ACCEPT"))
            self.assertTrue(rec["accepted"])
            self.assertTrue(rec["landed"])
            queued = ctrl.founder_queue()
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0]["task_id"], "t_ok")
            self.assertFalse(os.path.exists(sentinel) and os.path.getsize(sentinel) > 0,
                             "dispatch() must not write to SL.FOUNDER_QUEUE's default")
            self.assertEqual(SL.FOUNDER_QUEUE, sentinel, "the default must be restored after dispatch()")
        finally:
            SL.FOUNDER_QUEUE = orig_default

    def test_run_dispatches_whole_backlog(self):
        out = self._ctrl([self._task("a", "ACCEPT"), self._task("b", "INTEGRITY"),
                          self._task("c", "tests-fail")]).run()
        self.assertEqual(out["attempted"], 3)
        self.assertEqual(out["accepted"], 1)
        self.assertEqual(out["landed"], 1)
        self.assertEqual(out["stopped_reason"], "completed")
        self.assertEqual(len(CALLS), 3)

    def test_throwing_worker_contained(self):
        out = self._ctrl([self._task("boom", "BOOM"), self._task("ok2", "ACCEPT")]).run()
        self.assertEqual(out["attempted"], 2)  # the throw did not kill the controller
        self.assertEqual(out["accepted"], 1)

    # -- cap enforcement -------------------------------------------------------
    def test_max_tasks_cap_truncates(self):
        backlog = [self._task(f"f{i}", "tests-fail") for i in range(8)]
        out = self._ctrl(backlog, cfg=SL.LoopConfig(max_tasks=2)).run()
        self.assertEqual(out["attempted"], 2)
        self.assertEqual(out["skipped"], 6)

    def test_per_task_budget_forwarded_to_worker(self):
        cfg = SL.LoopConfig(max_tasks=10, budget_per_task=7, timeout=123)
        self._ctrl([self._task("t1", "tests-fail"),
                    self._task("t2", "tests-fail", budget=2)], cfg=cfg).run()
        self.assertEqual(CALLS[0]["budget"], 7, "cfg default budget forwarded")
        self.assertEqual(CALLS[0]["timeout"], 123)
        self.assertEqual(CALLS[1]["budget"], 2, "per-task budget override forwarded")

    # -- accept-rate floor -----------------------------------------------------
    def test_accept_rate_floor_bails_early(self):
        backlog = [self._task(f"f{i}", "tests-fail") for i in range(8)]
        cfg = SL.LoopConfig(max_tasks=8, min_accept_rate=0.5, floor_after=3)
        out = self._ctrl(backlog, cfg=cfg).run()
        self.assertEqual(out["attempted"], 3)
        self.assertIn("accept_rate_floor", out["stopped_reason"])
        self.assertEqual(out["skipped"], 5)

    def test_rate_above_floor_completes(self):
        backlog = [self._task("a1", "ACCEPT"), self._task("f1", "tests-fail"),
                   self._task("a2", "ACCEPT"), self._task("f2", "tests-fail"),
                   self._task("a3", "ACCEPT")]
        cfg = SL.LoopConfig(max_tasks=8, min_accept_rate=0.5, floor_after=3)
        out = self._ctrl(backlog, cfg=cfg).run()
        self.assertEqual(out["attempted"], 5)
        self.assertEqual(out["stopped_reason"], "completed")

    # -- founder queue ---------------------------------------------------------
    def test_accepted_landed_is_queued_for_founder(self):
        ctrl = self._ctrl([self._task("t_ok", "ACCEPT")])
        ctrl.run()
        queued = ctrl.founder_queue()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["task_id"], "t_ok")
        self.assertIn("founder", queued[0]["action"])

    def test_accepted_not_landed_is_not_queued(self):
        ctrl = self._ctrl([self._task("t_noland", "NOLAND")])
        out = ctrl.run()
        self.assertEqual(out["accepted"], 1)
        self.assertEqual(out["landed"], 0)
        self.assertEqual(ctrl.founder_queue(), [], "accepted-but-not-landed must NOT be queued")

    def test_integrity_violation_not_queued(self):
        ctrl = self._ctrl([self._task("t_bad", "INTEGRITY")])
        ctrl.run()
        self.assertEqual(ctrl.founder_queue(), [], "integrity violation never reaches the founder")

    def test_controller_never_merges(self):
        # the queue action is review+merge BY THE FOUNDER — the controller only enqueues, never merges.
        ctrl = self._ctrl([self._task("t_ok", "ACCEPT")])
        ctrl.run()
        self.assertIn("(founder gate)", ctrl.founder_queue()[0]["action"])

    def test_founder_queue_empty_when_no_file(self):
        ctrl = self._ctrl([self._task("f", "tests-fail")])
        ctrl.run()
        self.assertEqual(ctrl.founder_queue(), [], "no landed PR → no queue file → empty list, no crash")

    # -- route table + the two-plane wiring ------------------------------------
    def test_load_real_route_table(self):
        routes, warnings = C.load_route_table()
        self.assertTrue(any(r.get("id") == "seif-source-fix" for r in routes),
                        "the shipped 01_routes/seif-source-fix.yaml must load")

    def test_load_route_table_missing_dir_is_warned_not_fatal(self):
        routes, warnings = C.load_route_table(os.path.join(self.tmp, "no-such-dir"))
        self.assertEqual(routes, [])
        self.assertTrue(warnings and "absent" in warnings[0])

    def test_load_route_table_skips_non_route_yaml(self):
        rdir = os.path.join(self.tmp, "routes")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "junk.yaml"), "w") as f:
            f.write("just: a plain mapping\n")
        with open(os.path.join(rdir, "good.yaml"), "w") as f:
            f.write("schema: efl.route/v1\nid: r1\nmatch:\n  intents: [fix]\n")
        routes, warnings = C.load_route_table(rdir)
        self.assertEqual([r["id"] for r in routes], ["r1"])
        self.assertTrue(any("junk.yaml" in w for w in warnings))

    def test_route_for_matches_by_intent(self):
        ctrl = self._ctrl([])
        chosen = ctrl.route_for({"task_id": "t", "intent": "fix"})
        self.assertEqual(chosen["id"], "test-fix-route")

    def test_route_for_explicit_id_wins(self):
        ctrl = self._ctrl([])
        chosen = ctrl.route_for({"task_id": "t", "route": "test-fix-route"})
        self.assertEqual(chosen["id"], "test-fix-route")

    def test_route_for_no_match_returns_none(self):
        ctrl = self._ctrl([])
        self.assertIsNone(ctrl.route_for({"task_id": "t", "intent": "deploy"}))

    def test_compile_for_produces_lean_flags(self):
        ctrl = self._ctrl([])
        compiled = ctrl.compile_for({"task_id": "t", "intent": "fix"})
        self.assertIsNotNone(compiled)
        self.assertIn("--strict-mcp-config", compiled["lean_flags"])
        self.assertEqual(compiled["model"], ECP.MODEL_IDS["claude-haiku"])

    def test_compile_for_no_route_returns_none(self):
        ctrl = self._ctrl([])
        self.assertIsNone(ctrl.compile_for({"task_id": "t", "intent": "deploy"}))

    # -- worker adapter: route forwarding --------------------------------------
    def test_worker_adapter_forwards_route_when_accepted(self):
        seen = {}

        def route_aware(repo, prompt, test_cmd, route=None, **kw):
            seen["route"] = route
            return {"accepted": False, "reason": "tests", "patch": ""}

        C._invoke_worker(route_aware, "/r", "fix it", "x", route={"id": "X"})
        self.assertEqual(seen["route"], {"id": "X"})

    def test_worker_adapter_drops_route_for_unaware_worker(self):
        # a fake worker with no `route` param and no **kw must NOT receive route= (would TypeError)
        def route_blind(repo, prompt, test_cmd, budget=3, timeout=600, make_pr=True, protected=None):
            return {"accepted": False, "reason": "tests", "patch": ""}

        # must not raise even though we pass a route to the adapter
        out = C._invoke_worker(route_blind, "/r", "fix it", "x", route={"id": "X"})
        self.assertEqual(out["reason"], "tests")

    def test_route_runner_injects_compiled_route_into_real_worker(self):
        # fake_worker DOES accept route=; a 'fix' task must arrive at the worker with a matched route.
        ctrl = self._ctrl([self._task("t_fix", "fix the bug then INTEGRITY")])
        ctrl.run()
        self.assertEqual(len(CALLS), 1)
        self.assertIsNotNone(CALLS[0]["route"], "a fix task routes to a matching route")
        self.assertEqual(CALLS[0]["route"]["id"], "test-fix-route")

    def test_route_runner_passes_none_when_no_route_matches(self):
        # a task whose prompt has no routable verb AND no task-level route → un-routed worker
        ctrl = self._ctrl([self._task("t_plain", "ACCEPT this please")])
        ctrl.run()
        self.assertIsNone(CALLS[0]["route"])

    def test_explicit_task_route_honored_end_to_end(self):
        # a task whose prompt has NO routable verb but carries an explicit route id must STILL arrive at
        # the worker with that route — proving dispatch honors task-level routing, not just the prompt verb.
        ctrl = self._ctrl([self._task("t_expl", "ACCEPT this please", route="test-fix-route")])
        ctrl.run()
        self.assertIsNotNone(CALLS[0]["route"], "explicit task route must reach the worker")
        self.assertEqual(CALLS[0]["route"]["id"], "test-fix-route")

    def test_task_path_match_honored_end_to_end(self):
        # path-based routing: a non-verb prompt + a task `path` under the route's globs must route by PATH.
        ctrl = self._ctrl([self._task("t_path", "ACCEPT this please", path="logos/x.py")])
        ctrl.run()
        self.assertIsNotNone(CALLS[0]["route"], "path-matched task route must reach the worker")
        self.assertEqual(CALLS[0]["route"]["id"], "test-fix-route")

    def test_explicit_dict_route_overrides_prompt_inference(self):
        # an inline route dict on the task wins over any prompt-verb inference.
        inline = {"schema": ECP.SCHEMA, "id": "inline-route", "match": {"intents": ["fix"]}}
        ctrl = self._ctrl([self._task("t_inline", "fix the bug then ACCEPT", route=inline)])
        ctrl.run()
        self.assertEqual(CALLS[0]["route"]["id"], "inline-route")

    # -- dry-run plane ---------------------------------------------------------
    def test_dry_run_uses_fake_worker_no_real_runner(self):
        # dry_run=True installs make_dry_runner; ACCEPT lands + queues with no real seif_run call
        ctrl = C.Controller([self._task("d", "ACCEPT")], routes=[SAMPLE_ROUTE], mem=self.mem,
                            cfg=SL.LoopConfig(max_tasks=5), dry_run=True, queue_path=self.qpath)
        out = ctrl.run()
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["accepted"], 1)
        self.assertEqual(len(ctrl.founder_queue()), 1)

    def test_dry_runner_scripts_outcomes_by_keyword(self):
        run = C.make_dry_runner()
        self.assertTrue(run("/r", "ACCEPT", "x")["accepted"])
        self.assertFalse(run("/r", "NOLAND", "x")["landed"])
        self.assertEqual(run("/r", "INTEGRITY", "x")["reason"], "integrity_violation")
        self.assertEqual(run("/r", "nothing special", "x")["reason"], "tests")
        with self.assertRaises(RuntimeError):
            run("/r", "BOOM", "x")

    def test_dry_runner_ignores_injected_route_kwarg(self):
        run = C.make_dry_runner()
        # the route-injecting adapter may pass route=…; the dry runner must accept and ignore it
        self.assertTrue(C._invoke_worker(run, "/r", "ACCEPT", "x", route={"id": "X"})["accepted"])

    # -- infer_intent helper ---------------------------------------------------
    def test_infer_intent_maps_leading_verb(self):
        self.assertEqual(C._infer_intent("Fix the parser"), "fix")
        self.assertEqual(C._infer_intent("debug the crash"), "debug")
        self.assertEqual(C._infer_intent("Implement the controller"), "add")
        self.assertIsNone(C._infer_intent("the thing is broken"))


if __name__ == "__main__":
    unittest.main()
