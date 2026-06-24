"""unittest for the ECP route compiler (logos/ecp_route.py) — pure, no I/O, no claude.

Pins the measured-lever derivation: cheap default → FULL lean (setting-sources project + strict-mcp);
pinned strong model → mcp-only lean + a warning (the −54% user-config lever can't coexist with a pinned
strong model via these flags); tool/MCP policy; graph-selector context resolution + graceful degradation;
validation; and loading/matching the shipped sample route.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import ecp_route as R  # noqa: E402

ROUTE_DIR = os.path.join(os.path.dirname(__file__), "..", "01_routes")


def _route(**over):
    base = {"schema": "efl.route/v1", "id": "r", "match": {"intents": ["fix"]},
            "tools": {"allow": ["Read", "Edit"], "deny": ["Bash(git push *)"], "mcp": []},
            "budget": {"requested_model": "claude-haiku", "max_turns": 3}}
    base.update(over)
    return base


class ValidateTest(unittest.TestCase):
    def test_valid_route_has_no_problems(self):
        self.assertEqual(R.validate_route(_route()), [])

    def test_bad_schema_and_missing_match(self):
        probs = R.validate_route({"schema": "wrong", "id": "x", "match": {}})
        self.assertTrue(any("schema" in p for p in probs))
        self.assertTrue(any("match" in p for p in probs))

    def test_compile_rejects_invalid(self):
        with self.assertRaises(ValueError):
            R.compile_route({"schema": "nope"})


class MalformedInputTest(unittest.TestCase):
    def test_non_dict_subobjects_rejected_cleanly(self):
        for bad in [{"schema": "efl.route/v1", "id": "r", "match": "fix"},          # match not a mapping
                    {"schema": "efl.route/v1", "id": "r", "match": {"intents": ["x"]}, "tools": ["Read"]},  # tools list
                    {"schema": "efl.route/v1", "id": "r", "match": {"intents": ["x"]}, "budget": "opus"}]:  # budget str
            self.assertTrue(R.validate_route(bad), f"expected problems for {bad}")
            with self.assertRaises(ValueError):
                R.compile_route(bad)            # clean ValueError, not AttributeError

    def test_malformed_graph_does_not_crash(self):
        route = _route(context={"selectors": [{"graph": {"seeds": "${changed_files}", "edges": ["imports"], "max_hops": 2}}]})
        for bad_graph in ["not a graph", {"nodes": "x"}, {"links": [1, 2]}, {"nodes": 5}, {"links": None}, {}]:
            c = R.compile_route(route, changed_files=["src/core.py"], graph=bad_graph)
            self.assertIn("src/core.py", c["context_files"])   # degrades to seeds, never raises

    def test_malformed_selectors_and_required_do_not_crash(self):
        good_graph = {"nodes": [{"id": "core", "source_file": "src/core.py"}], "links": []}
        for ctx in [
            {"required": 5, "selectors": [{"graph": "x"}]},                 # required non-list, graph non-dict
            {"selectors": [{"graph": {"seeds": 5, "edges": "imports", "max_hops": "deep"}}]},  # all wrong types
            {"selectors": ["nope", 7, {"nograph": 1}]},                     # junk selectors
        ]:
            c = R.compile_route(_route(context=ctx), changed_files=["src/core.py"], graph=good_graph)
            self.assertIsInstance(c["context_files"], list)                 # never raises

    def test_none_subobjects_are_absent_not_crash(self):
        # None = "absent" (legitimately valid) → compiles cleanly, no AttributeError on dict(None)
        route = {"schema": "efl.route/v1", "id": "r", "match": {"intents": ["fix"]},
                 "budget": None, "context": None, "tools": None, "memory": None, "verification": None}
        self.assertEqual(R.validate_route(route), [])
        c = R.compile_route(route)
        self.assertEqual(c["model"], "claude-haiku-4-5-20251001")   # None budget → cheap default
        self.assertEqual(c["lean"], "full")
        self.assertEqual(c["context_files"], [])
        self.assertEqual(c["tool_policy"], {"allow": [], "deny": []})


class LeverDerivationTest(unittest.TestCase):
    def test_cheap_default_gets_full_lean(self):
        c = R.compile_route(_route())
        self.assertEqual(c["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(c["lean"], "full")
        self.assertIn("--strict-mcp-config", c["claude_argv"])         # ~43% MCP lever
        self.assertIn("--setting-sources", c["claude_argv"])           # ~54% user-config lever
        self.assertIn("project", c["claude_argv"])
        self.assertEqual(c["warnings"], [])

    def test_pinned_opus_is_mcp_only_lean_with_warning(self):
        c = R.compile_route(_route(budget={"requested_model": "claude-opus"}))
        self.assertEqual(c["model"], "claude-opus-4-8")
        self.assertEqual(c["lean"], "mcp-only")
        self.assertIn("--strict-mcp-config", c["claude_argv"])         # still get the MCP lever
        self.assertNotIn("--setting-sources", c["claude_argv"])        # but NOT the user-config one (measured)
        self.assertTrue(c["warnings"])                                 # tradeoff stated, not hidden

    def test_tool_policy_becomes_allow_deny_flags(self):
        c = R.compile_route(_route())
        self.assertIn("--allowedTools", c["claude_argv"])
        self.assertIn("Read", c["claude_argv"])
        self.assertIn("--disallowedTools", c["claude_argv"])
        self.assertIn("Bash(git push *)", c["claude_argv"])


class ContextResolutionTest(unittest.TestCase):
    GRAPH = {"nodes": [{"id": "core", "source_file": "src/core.py"},
                       {"id": "mid", "source_file": "src/mid.py"},
                       {"id": "app", "source_file": "src/app.py"}],
             "links": [{"source": "mid", "target": "core", "relation": "imports"},
                       {"source": "app", "target": "mid", "relation": "imports"}]}

    def test_required_plus_graph_closure(self):
        route = _route(context={"required": ["docs/X.md"],
                                "selectors": [{"graph": {"seeds": "${changed_files}", "edges": ["imports"], "max_hops": 2}}]})
        c = R.compile_route(route, changed_files=["src/core.py"], graph=self.GRAPH)
        self.assertIn("docs/X.md", c["context_files"])
        # reverse-import closure of core: mid imports core, app imports mid → both pulled in
        self.assertIn("src/mid.py", c["context_files"])
        self.assertIn("src/app.py", c["context_files"])
        self.assertEqual(c["context_unresolved"], [])

    def test_degrades_without_graph(self):
        route = _route(context={"selectors": [{"graph": {"seeds": "${changed_files}", "edges": ["imports"], "max_hops": 2}}]})
        c = R.compile_route(route, changed_files=["src/core.py"], graph=None)
        self.assertIn("src/core.py", c["context_files"])      # falls back to the seeds
        self.assertTrue(c["context_unresolved"])              # records that it couldn't expand


class SampleRouteTest(unittest.TestCase):
    def test_shipped_route_loads_compiles_and_matches(self):
        route = R.load_route(os.path.join(ROUTE_DIR, "seif-source-fix.yaml"))
        self.assertEqual(R.validate_route(route), [])
        c = R.compile_route(route, changed_files=["logos/usage_meter.py"])
        self.assertEqual(c["lean"], "full")                  # cheap default
        self.assertEqual(c["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(R.match_route([route], intent="fix", path="logos/x.py")["id"], "seif-source-fix")
        self.assertIsNone(R.match_route([route], intent="deploy"))


if __name__ == "__main__":
    unittest.main()
