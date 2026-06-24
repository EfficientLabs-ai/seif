"""unittest for ECP → loop integration (seif_run route= opt-in).

Proves a route compiles into the per-task minimum environment and that its lean flags + routed model reach
the chokepoint; and that the default (route=None) passes nothing (zero behavior change). _claude_edit is
mocked (no real claude); the L4/receipt ledgers are pinned to temp so the test is hermetic.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
import seif_run as SR  # noqa: E402
import project_harness as H  # noqa: E402
import checkpoint as CP  # noqa: E402

ROUTE = {"schema": "efl.route/v1", "id": "r-test", "match": {"intents": ["fix"]},
         "tools": {"allow": ["Read", "Edit"], "deny": ["Bash(git push *)"], "mcp": []},
         "budget": {"requested_model": "claude-haiku", "max_turns": 2}}


class EcpLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-ecpwire-")
        self._h, self._l, self._f = H.RECEIPTS, CP.LEDGER, CP.FAILURES
        H.RECEIPTS = os.path.join(self.tmp, "rcpt.jsonl")
        CP.LEDGER = os.path.join(self.tmp, "cp.jsonl")
        CP.FAILURES = os.path.join(self.tmp, "fail.jsonl")
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "x.py"), "w").write("def f():\n    return 1\n")
        g = lambda *a: subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True)
        g("add", "-A"); g("commit", "-qm", "base")

    def tearDown(self):
        H.RECEIPTS, CP.LEDGER, CP.FAILURES = self._h, self._l, self._f
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_route_compiles_and_passes_lean_flags_and_model(self):
        cap = {}

        def fake_edit(wt, task, feedback, first, timeout, model=None, extra_flags=None):
            cap["model"], cap["extra_flags"] = model, extra_flags
            return 0, SR.UM.empty()          # no file change → loop stops cleanly at step 1

        with mock.patch.object(SR, "_claude_edit", side_effect=fake_edit):
            r = SR.seif_run(self.repo, "fix it", "true", make_pr=False, route=ROUTE)
        self.assertFalse(r["accepted"])       # no change → not accepted (expected)
        self.assertEqual(cap["model"], "claude-haiku-4-5-20251001")   # routed model
        self.assertIn("--strict-mcp-config", cap["extra_flags"])      # ~43% lever
        self.assertIn("--setting-sources", cap["extra_flags"])        # ~54% lever (cheap default → full lean)
        self.assertIn("Read", cap["extra_flags"])                     # route tool allowlist

    def test_explicit_model_arg_overrides_route(self):
        cap = {}

        def fake_edit(wt, task, feedback, first, timeout, model=None, extra_flags=None):
            cap["model"] = model
            return 0, SR.UM.empty()
        with mock.patch.object(SR, "_claude_edit", side_effect=fake_edit):
            SR.seif_run(self.repo, "fix", "true", make_pr=False, route=ROUTE, model="claude-opus-4-8")
        self.assertEqual(cap["model"], "claude-opus-4-8")             # explicit arg wins over route

    def test_kill_switch_route_false_passes_no_extra_flags(self):
        # route=False is the explicit kill-switch — auto-select is bypassed, no flags reach the chokepoint.
        cap = {}

        def fake_edit(wt, task, feedback, first, timeout, model=None, extra_flags=None):
            cap["extra_flags"] = extra_flags
            return 0, SR.UM.empty()
        with mock.patch.object(SR, "_claude_edit", side_effect=fake_edit):
            SR.seif_run(self.repo, "fix", "true", make_pr=False, route=False)   # kill-switch
        self.assertIsNone(cap["extra_flags"])                        # disabled → no route applied

    def test_kill_switch_env_var_passes_no_extra_flags(self):
        # SEIF_NO_ROUTE=1 is the env kill-switch — equivalent to route=False even with route=None (default).
        cap = {}

        def fake_edit(wt, task, feedback, first, timeout, model=None, extra_flags=None):
            cap["extra_flags"] = extra_flags
            return 0, SR.UM.empty()
        with mock.patch.dict(os.environ, {"SEIF_NO_ROUTE": "1"}):
            with mock.patch.object(SR, "_claude_edit", side_effect=fake_edit):
                SR.seif_run(self.repo, "fix", "true", make_pr=False)            # default route=None
        self.assertIsNone(cap["extra_flags"])                        # env kill-switch wins

    def test_auto_select_default_applies_matching_route(self):
        # route=None (default) now AUTO-selects: a matching route's lean flags reach the chokepoint without
        # any opt-in. We pin _load_routes to a controlled set so the test is hermetic + independent of disk.
        cap = {}

        def fake_edit(wt, task, feedback, first, timeout, model=None, extra_flags=None):
            cap["model"], cap["extra_flags"] = model, extra_flags
            return 0, SR.UM.empty()
        with mock.patch.object(SR, "_load_routes", return_value=[ROUTE]):
            with mock.patch.object(SR, "_claude_edit", side_effect=fake_edit):
                # task == "fix" matches ROUTE's match.intents=["fix"] via match_route(intent=task)
                r = SR.seif_run(self.repo, "fix", "true", make_pr=False)
        self.assertEqual(cap["model"], "claude-haiku-4-5-20251001")            # routed model auto-applied
        self.assertIn("--strict-mcp-config", cap["extra_flags"])               # lean flags auto-applied
        self.assertEqual(r["route_id_selected"], "r-test")                     # selected route recorded

    def test_auto_select_no_match_keeps_default_behavior(self):
        # route=None + no matching route → current (full) behavior: no flags, route_id_selected='none'.
        cap = {}

        def fake_edit(wt, task, feedback, first, timeout, model=None, extra_flags=None):
            cap["extra_flags"] = extra_flags
            return 0, SR.UM.empty()
        with mock.patch.object(SR, "_load_routes", return_value=[ROUTE]):
            with mock.patch.object(SR, "_claude_edit", side_effect=fake_edit):
                # task "deploy the thing" matches no route's intents → unmatched → default behavior
                r = SR.seif_run(self.repo, "deploy the thing", "true", make_pr=False)
        self.assertIsNone(cap["extra_flags"])                        # no route → no behavior change
        self.assertEqual(r["route_id_selected"], "none")


if __name__ == "__main__":
    unittest.main()
