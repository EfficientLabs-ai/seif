"""unittest for A3 route auto-select default-on in seif_run.

Auto-select is now the DEFAULT (route=None): seif_run loads 01_routes/*.yaml, calls
match_route(routes, intent=task), and on a hit compiles + applies the route (lean flags + routed model +
budget) exactly like the explicit-route branch; on a miss it keeps current (full) behavior. Kill-switch:
route=False OR env SEIF_NO_ROUTE=1. route_id_selected ('none' when unmatched) is recorded on the result.

Coverage:
  - _load_routes loads + validates real manifests, skips junk, no-throws on a missing dir;
  - auto-select HIT: matching intent → lean flags + routed model reach the chokepoint, route_id recorded;
  - no-match FALLBACK: unmatched intent → no flags, route_id_selected='none';
  - kill-switch route=False and env SEIF_NO_ROUTE=1 both bypass auto-select even with a matching route;
  - explicit route still wins and the explicit-model arg still overrides a routed model;
  - compile_route's measured constraint is preserved (cheap default → full lean; pinned strong → mcp-only).
Hermetic: _load_routes / _claude_edit injected; ledgers pinned to temp; no remote (no PR).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import seif_run as SR  # noqa: E402
import project_harness as H  # noqa: E402
import checkpoint as CP  # noqa: E402
import ecp_route as ECP  # noqa: E402

# a cheap-default route (haiku) → FULL lean; intent "fix" so match_route(intent="fix") hits.
CHEAP_ROUTE = {"schema": "efl.route/v1", "id": "r-cheap", "match": {"intents": ["fix", "debug"]},
               "tools": {"allow": ["Read", "Edit"], "deny": ["Bash(git push *)"], "mcp": []},
               "budget": {"requested_model": "claude-haiku", "max_turns": 2}}
# a pinned-strong route (opus) → mcp-only lean + warning (constraint compile_route encodes).
STRONG_ROUTE = {"schema": "efl.route/v1", "id": "r-strong", "match": {"intents": ["refactor"]},
                "tools": {"mcp": []}, "budget": {"requested_model": "claude-opus", "max_turns": 4}}


class LoadRoutesUnitTest(unittest.TestCase):
    def test_loads_and_validates_real_manifests(self):
        routes = SR._load_routes()                            # default ROUTES_DIR = repo 01_routes
        ids = [r.get("id") for r in routes]
        self.assertIn("seif-source-fix", ids)                # the shipped route is discovered
        for r in routes:
            self.assertEqual(ECP.validate_route(r), [])      # only well-formed routes are returned

    def test_missing_dir_returns_empty_no_throw(self):
        self.assertEqual(SR._load_routes("/no/such/routes/dir"), [])

    def test_skips_non_yaml_and_invalid_manifests(self):
        d = tempfile.mkdtemp(prefix="t-routes-")
        try:
            open(os.path.join(d, "good.yaml"), "w").write(
                "schema: efl.route/v1\nid: good\nmatch: {intents: [fix]}\n")
            open(os.path.join(d, "bad.yaml"), "w").write("schema: wrong\nid: bad\n")  # invalid → skipped
            open(os.path.join(d, "notes.txt"), "w").write("ignored\n")               # non-yaml → skipped
            ids = [r.get("id") for r in SR._load_routes(d)]
            self.assertEqual(ids, ["good"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class AutoSelectLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-autosel-")
        self._h, self._l, self._f = H.RECEIPTS, CP.LEDGER, CP.FAILURES
        H.RECEIPTS = os.path.join(self.tmp, "r.jsonl")
        CP.LEDGER = os.path.join(self.tmp, "c.jsonl")
        CP.FAILURES = os.path.join(self.tmp, "f.jsonl")
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "x.py"), "w").write("def f():\n    return 1\n")
        g = lambda *a: subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True)
        g("add", "-A"); g("commit", "-qm", "base")

    def tearDown(self):
        H.RECEIPTS, CP.LEDGER, CP.FAILURES = self._h, self._l, self._f
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _spy(self, cap):
        def fake_edit(wt, task, feedback, first, timeout, model=None, extra_flags=None):
            cap["model"], cap["extra_flags"] = model, extra_flags
            return 0, SR.UM.empty()                           # no change → loop stops cleanly at step 1
        return fake_edit

    def test_auto_select_hit_applies_route(self):
        cap = {}
        with mock.patch.object(SR, "_load_routes", return_value=[CHEAP_ROUTE]):
            with mock.patch.object(SR, "_claude_edit", side_effect=self._spy(cap)):
                r = SR.seif_run(self.repo, "fix", "true", make_pr=False)   # route=None default → auto
        self.assertEqual(cap["model"], "claude-haiku-4-5-20251001")        # routed cheap model
        self.assertIn("--strict-mcp-config", cap["extra_flags"])           # ~43% MCP lever
        self.assertIn("--setting-sources", cap["extra_flags"])             # ~54% lever (cheap → full lean)
        self.assertIn("Read", cap["extra_flags"])                          # route tool allowlist
        self.assertEqual(r["route_id_selected"], "r-cheap")

    def test_auto_select_no_match_keeps_full_behavior(self):
        cap = {}
        with mock.patch.object(SR, "_load_routes", return_value=[CHEAP_ROUTE]):
            with mock.patch.object(SR, "_claude_edit", side_effect=self._spy(cap)):
                r = SR.seif_run(self.repo, "deploy to prod", "true", make_pr=False)  # no intent match
        self.assertIsNone(cap["extra_flags"])                              # default behavior preserved
        self.assertIsNone(cap["model"])
        self.assertEqual(r["route_id_selected"], "none")

    def test_kill_switch_route_false_bypasses_auto_select(self):
        cap = {}
        with mock.patch.object(SR, "_load_routes", return_value=[CHEAP_ROUTE]) as load:
            with mock.patch.object(SR, "_claude_edit", side_effect=self._spy(cap)):
                r = SR.seif_run(self.repo, "fix", "true", make_pr=False, route=False)  # kill-switch
        self.assertIsNone(cap["extra_flags"])                              # no route applied
        self.assertEqual(r["route_id_selected"], "none")
        load.assert_not_called()                                          # auto-select never even loaded

    def test_kill_switch_env_var_bypasses_auto_select(self):
        cap = {}
        with mock.patch.dict(os.environ, {"SEIF_NO_ROUTE": "1"}):
            with mock.patch.object(SR, "_load_routes", return_value=[CHEAP_ROUTE]) as load:
                with mock.patch.object(SR, "_claude_edit", side_effect=self._spy(cap)):
                    r = SR.seif_run(self.repo, "fix", "true", make_pr=False)  # default, env disables
        self.assertIsNone(cap["extra_flags"])
        self.assertEqual(r["route_id_selected"], "none")
        load.assert_not_called()

    def test_explicit_route_still_wins_over_auto(self):
        cap = {}
        # explicit route is honored; _load_routes (auto path) must NOT be consulted.
        with mock.patch.object(SR, "_load_routes", return_value=[STRONG_ROUTE]) as load:
            with mock.patch.object(SR, "_claude_edit", side_effect=self._spy(cap)):
                r = SR.seif_run(self.repo, "anything", "true", make_pr=False, route=CHEAP_ROUTE)
        self.assertEqual(r["route_id_selected"], "r-cheap")
        self.assertIn("--strict-mcp-config", cap["extra_flags"])
        load.assert_not_called()

    def test_explicit_model_arg_overrides_auto_routed_model(self):
        cap = {}
        with mock.patch.object(SR, "_load_routes", return_value=[CHEAP_ROUTE]):
            with mock.patch.object(SR, "_claude_edit", side_effect=self._spy(cap)):
                SR.seif_run(self.repo, "fix", "true", make_pr=False, model="claude-opus-4-8")
        self.assertEqual(cap["model"], "claude-opus-4-8")                  # explicit model beats route

    def test_pinned_strong_route_constraint_is_preserved(self):
        # compile_route's measured constraint: a pinned strong model keeps user settings (no --setting-sources)
        # and warns. Auto-select must apply the SAME compiled flags as the explicit branch.
        cap = {}
        with mock.patch.object(SR, "_load_routes", return_value=[STRONG_ROUTE]):
            with mock.patch.object(SR, "_claude_edit", side_effect=self._spy(cap)):
                r = SR.seif_run(self.repo, "refactor", "true", make_pr=False)
        self.assertEqual(cap["model"], "claude-opus-4-8")                  # pinned strong (opus)
        self.assertIn("--strict-mcp-config", cap["extra_flags"])           # mcp lever still applies
        self.assertNotIn("--setting-sources", cap["extra_flags"])          # but NOT the user-config lever
        self.assertEqual(r["route_id_selected"], "r-strong")


if __name__ == "__main__":
    unittest.main()
