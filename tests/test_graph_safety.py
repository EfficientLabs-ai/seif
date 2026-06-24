"""unittest for logos/graph_safety.py — REGRESSION-SAFETY over the code graph (measured ~0% token effect).

graph_safety is PURE composition over memory/tripartite.py SemanticMemory (via logos/delta_plan._blast_radius):

  invalidation(repo, changed)   = reverse-import closure: dependent modules whose tests must re-run.
  test_selection(repo, changed) = the minimal TEST subset (changed tests ∪ test files among the closure),
                                  or None when the graph can't answer (caller MUST fall back to full suite).
  blast_radius(repo, changed)   = delegates verbatim to delta_plan._blast_radius (single source of truth).

These tests prove the happy path against a synthetic graph, the union over multiple changed files, the
critical None-vs-[] distinction (cannot-know vs nothing), and the OPTIONAL, default-OFF fast-path wired
into project_harness.run_tests (full suite stays the default + final gate).
"""
import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import delta_plan  # noqa: E402  (the canonical _blast_radius graph_safety delegates to)
import graph_safety  # noqa: E402
import project_harness as PH  # noqa: E402


def _graph(repo):
    """Synthetic graphify-out: app -> mid -> core (imports). Plus TEST nodes that import the modules:
        tests/test_core.py -> core,  tests/test_app.py -> app,  src/loner.py is unconnected.
    A reverse-closure from core therefore reaches mid, app, AND the two tests that (transitively) import it."""
    os.makedirs(os.path.join(repo, "graphify-out"))
    g = {"directed": False,
         "nodes": [{"id": "core", "source_file": "src/core.py", "label": "core.py"},
                   {"id": "mid", "source_file": "src/mid.py", "label": "mid.py"},
                   {"id": "app", "source_file": "src/app.py", "label": "app.py"},
                   {"id": "loner", "source_file": "src/loner.py", "label": "loner.py"},
                   {"id": "tcore", "source_file": "tests/test_core.py", "label": "test_core.py"},
                   {"id": "tapp", "source_file": "tests/test_app.py", "label": "test_app.py"}],
         "links": [{"source": "mid", "target": "core", "relation": "imports_from"},
                   {"source": "app", "target": "mid", "relation": "imports_from"},
                   {"source": "tcore", "target": "core", "relation": "imports_from"},
                   {"source": "tapp", "target": "app", "relation": "imports_from"}],
         "built_at_commit": "deadbeef"}
    with open(os.path.join(repo, "graphify-out", "graph.json"), "w") as f:
        json.dump(g, f)


class GraphSafetyTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="t-gsafety-")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    # ---- invalidation = reverse-import closure of the changed files ----
    def test_invalidation_reverse_closure(self):
        _graph(self.repo)
        # change core.py → everything that imports it (directly or transitively): mid, app, both tests.
        inv = graph_safety.invalidation(self.repo, ["src/core.py"])
        self.assertEqual(inv, ["src/app.py", "src/mid.py", "tests/test_app.py", "tests/test_core.py"])

    def test_invalidation_unions_changed_files(self):
        _graph(self.repo)
        inv = graph_safety.invalidation(self.repo, ["src/core.py", "src/mid.py"])
        # union of both reverse closures, sorted + de-duped
        self.assertEqual(inv, ["src/app.py", "src/mid.py", "tests/test_app.py", "tests/test_core.py"])

    def test_invalidation_none_without_graph(self):
        # no graphify-out at all → cannot know → None (NOT [])
        self.assertIsNone(graph_safety.invalidation(self.repo, ["src/core.py"]))

    def test_invalidation_corrupt_graph_is_none(self):
        os.makedirs(os.path.join(self.repo, "graphify-out"))
        open(os.path.join(self.repo, "graphify-out", "graph.json"), "w").write("{ not json")
        self.assertIsNone(graph_safety.invalidation(self.repo, ["src/core.py"]),
                          "corrupt graph → None (unknown), never [] (nothing)")

    # ---- test_selection = changed tests ∪ test files in the closure ----
    def test_test_selection_picks_only_tests(self):
        _graph(self.repo)
        sel = graph_safety.test_selection(self.repo, ["src/core.py"])
        # closure reaches src/mid.py, src/app.py (NOT tests) and the two test files (kept)
        self.assertEqual(sel, ["tests/test_app.py", "tests/test_core.py"])

    def test_test_selection_includes_changed_test_files_themselves(self):
        _graph(self.repo)
        # editing a test file that isn't in any closure must still re-run that very test file
        sel = graph_safety.test_selection(self.repo, ["tests/test_standalone.py"])
        self.assertIn("tests/test_standalone.py", sel)

    def test_test_selection_none_when_graph_absent(self):
        # the safety contract: graph can't answer → None → caller MUST run the full suite, not skip
        self.assertIsNone(graph_safety.test_selection(self.repo, ["src/core.py"]))

    def test_test_selection_empty_when_change_touches_no_tests(self):
        _graph(self.repo)
        # loner.py has no dependents and is not a test → graph answers, but the test subset is empty []
        # (distinct from None: the graph DID answer; project_harness still defaults to full suite on []).
        sel = graph_safety.test_selection(self.repo, ["src/loner.py"])
        self.assertEqual(sel, [])

    # ---- blast_radius delegates to delta_plan._blast_radius (single source of truth) ----
    def test_blast_radius_matches_delta_plan(self):
        _graph(self.repo)
        for changed in (["src/core.py"], ["src/mid.py"], ["src/loner.py"], ["nope.py"]):
            self.assertEqual(graph_safety.blast_radius(self.repo, changed),
                             delta_plan._blast_radius(self.repo, changed),
                             f"blast_radius must delegate verbatim for {changed}")

    def test_blast_radius_none_without_graph(self):
        self.assertIsNone(graph_safety.blast_radius(self.repo, ["src/core.py"]))


class IsTestFileTest(unittest.TestCase):
    def test_classifies_test_files(self):
        for p in ("tests/test_core.py", "test_x.py", "foo_test.py", "conftest.py",
                  "test/sub/anything.py", "pkg/tests/helper.py"):
            self.assertTrue(graph_safety._is_test_file(p), p)

    def test_rejects_non_test_files(self):
        for p in ("src/core.py", "lib/util.py", "main.py", "", None, "testimony.py"):
            self.assertFalse(graph_safety._is_test_file(p), p)


class ProjectHarnessFastPathTest(unittest.TestCase):
    """The fast-path wired into project_harness.run_tests is OPT-IN and default-OFF; the FULL suite is the
    default. These tests prove: (1) default behaviour is byte-for-byte unchanged, (2) the fast-path only
    narrows when graph_safety returns a non-empty subset AND a select_fmt is supplied, (3) it falls back to
    the full command on every uncertain signal (no graph / empty / no fmt)."""

    def setUp(self):
        self.wt = tempfile.mkdtemp(prefix="t-ph-fast-")

    def tearDown(self):
        shutil.rmtree(self.wt, ignore_errors=True)

    def test_default_runs_full_command_unchanged(self):
        # No fast_path kwarg → behaves exactly as before, plus a benign metadata field reporting 'disabled'.
        r = PH.run_tests(self.wt, "exit 0")
        self.assertEqual(r["outcome"], "pass")
        self.assertEqual(r["exit_code"], 0)
        self.assertFalse(r["fast_path"]["used"])
        self.assertEqual(r["fast_path"]["reason"], "disabled")

    def test_fast_path_enabled_but_no_graph_falls_back_to_full(self):
        # fast_path=True but the worktree has no graph → graph_safety returns None → full command runs.
        r = PH.run_tests(self.wt, "exit 0", fast_path=True,
                         changed_files=["src/core.py"], select_fmt="pytest {tests}")
        self.assertEqual(r["outcome"], "pass")
        self.assertFalse(r["fast_path"]["used"])
        self.assertEqual(r["fast_path"]["reason"], "no_graph")

    def test_fast_path_scopes_command_when_graph_answers(self):
        _graph(self.wt)
        # capture the actual command by writing it to a file the test can read back
        marker = os.path.join(self.wt, "ran.txt")
        fmt = "printf '%s' '{tests}' > " + marker + " ; exit 0"
        r = PH.run_tests(self.wt, "echo FULL_SUITE > " + marker + " ; exit 0",
                         fast_path=True, changed_files=["src/core.py"], select_fmt=fmt)
        self.assertEqual(r["outcome"], "pass")
        self.assertTrue(r["fast_path"]["used"])
        self.assertEqual(r["fast_path"]["reason"], "scoped")
        self.assertEqual(r["fast_path"]["selected"], ["tests/test_app.py", "tests/test_core.py"])
        with open(marker) as f:
            ran = f.read()
        self.assertIn("tests/test_core.py", ran)
        self.assertIn("tests/test_app.py", ran)
        self.assertNotIn("FULL_SUITE", ran, "scoped run must NOT have executed the full-suite command")

    def test_fast_path_empty_subset_falls_back_to_full(self):
        _graph(self.wt)
        # loner.py touches no tests → empty subset → graph_safety answered [] → full command runs (safety).
        r = PH.run_tests(self.wt, "exit 0", fast_path=True,
                         changed_files=["src/loner.py"], select_fmt="pytest {tests}")
        self.assertFalse(r["fast_path"]["used"])
        self.assertEqual(r["fast_path"]["reason"], "empty")

    def test_fast_path_without_select_fmt_falls_back_to_full(self):
        _graph(self.wt)
        # graph answers a real subset, but no '{tests}' slot to splice into → cannot scope → full command.
        r = PH.run_tests(self.wt, "exit 0", fast_path=True,
                         changed_files=["src/core.py"], select_fmt="pytest")
        self.assertFalse(r["fast_path"]["used"])
        self.assertEqual(r["fast_path"]["reason"], "no_fmt")

    def test_fast_path_propagates_real_exit_code(self):
        _graph(self.wt)
        # a scoped run that fails must report fail (exit code is still ground truth in the fast-path).
        r = PH.run_tests(self.wt, "exit 0", fast_path=True, changed_files=["src/core.py"],
                         select_fmt="false # {tests}")
        self.assertEqual(r["outcome"], "fail")
        self.assertTrue(r["fast_path"]["used"])

    def test_fast_path_malformed_select_fmt_falls_back_not_raises(self):
        _graph(self.wt)
        # a select_fmt with a stray '{' (an unknown/unbalanced field) must NOT raise out of run_tests —
        # .format fails → degrade to the full command (reason='bad_fmt'), never crash the gate.
        r = PH.run_tests(self.wt, "exit 0", fast_path=True, changed_files=["src/core.py"],
                         select_fmt="pytest {tests} {oops")
        self.assertEqual(r["outcome"], "pass")        # the full 'exit 0' command ran
        self.assertFalse(r["fast_path"]["used"])
        self.assertEqual(r["fast_path"]["reason"], "bad_fmt")

    def test_fast_path_quotes_paths_with_shell_metacharacters(self):
        # a changed test path containing spaces + a shell metachar must be shlex-quoted so it is passed as a
        # SINGLE literal argument and cannot inject a command. We capture argv via "$@" in a tiny shell shim.
        os.makedirs(os.path.join(self.wt, "graphify-out"))
        evil = "tests/test a;touch INJECTED.py"   # space + ';' would split/inject if unquoted
        g = {"directed": False,
             "nodes": [{"id": "ev", "source_file": evil, "label": "evil"}],
             "links": [], "built_at_commit": "x"}
        with open(os.path.join(self.wt, "graphify-out", "graph.json"), "w") as f:
            json.dump(g, f)
        # changing the evil test file itself selects it (it's a test file under tests/)
        marker = os.path.join(self.wt, "argv.txt")
        # 'printf %s\n "$@"' prints each positional arg on its own line → we can count them
        fmt = 'printf "%s\\n" {tests} > ' + shlex.quote(marker) + ' ; exit 0'
        r = PH.run_tests(self.wt, "exit 0", fast_path=True, changed_files=[evil], select_fmt=fmt)
        self.assertTrue(r["fast_path"]["used"])
        self.assertEqual(r["fast_path"]["selected"], [evil])
        with open(marker) as f:
            printed = f.read()
        # the path arrived as ONE argument (one line), proving it was a single quoted token...
        self.assertEqual(printed.strip().splitlines(), [evil])
        # ...and the injected `touch INJECTED.py` never executed.
        self.assertFalse(os.path.exists(os.path.join(self.wt, "INJECTED.py")),
                         "shell metacharacters in a path must not inject a command")


if __name__ == "__main__":
    unittest.main()
