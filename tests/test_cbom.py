import importlib.util
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", "logos"))
import cbom as CBOM  # noqa: E402

# Load the hook script by path (it lives under integrations/, not on sys.path as a package).
_HOOK_PATH = os.path.join(_HERE, "..", "integrations", "claude", "hooks", "cbom_hook.py")
_spec = importlib.util.spec_from_file_location("cbom_hook", _HOOK_PATH)
HOOK = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HOOK)


def _fixture_cbom():
    """A representative CBOM: a CLAUDE.md, two skills, a plugin, a hook, two MCP servers, base, plus one
    item with an unknown kind (must surface as 'other', never be dropped)."""
    return CBOM.make_cbom([
        CBOM.make_item("user_config", "~/.claude/CLAUDE.md", tokens=1000, path="/x/CLAUDE.md", bytes_=4000),
        CBOM.make_item("skill", "graphify", tokens=200),
        CBOM.make_item("skill", "deep-research", tokens=300),
        CBOM.make_item("plugin", "superpowers", tokens=150),
        CBOM.make_item("hook", "SessionStart:cbom_hook.py", tokens=40),
        CBOM.make_item("mcp", "Notion", tokens=4000),
        CBOM.make_item("mcp", "Figma", tokens=3500),
        CBOM.make_item("base", "system-prompt", tokens=2000),
        CBOM.make_item("plugin-extra", "uncategorized-kind", tokens=11),
    ], generated_at="2026-06-24T00:00:00+00:00")


class TestSummarize(unittest.TestCase):
    def test_category_subtotals(self):
        s = CBOM.summarize(_fixture_cbom())
        self.assertEqual(s["skills"], 500)            # 200 + 300
        self.assertEqual(s["plugins"], 150)
        self.assertEqual(s["hooks"], 40)
        self.assertEqual(s["mcp"], 7500)              # 4000 + 3500
        self.assertEqual(s["base"], 2000)
        self.assertEqual(s["count"], 9)

    def test_user_config_is_claudemd_plus_skills_plugins_hooks(self):
        s = CBOM.summarize(_fixture_cbom())
        self.assertEqual(s["user_config"], 1000 + 500 + 150 + 40)

    def test_unknown_kind_surfaces_as_other_not_dropped(self):
        s = CBOM.summarize(_fixture_cbom())
        self.assertEqual(s["other"], 11)

    def test_total_equals_straight_item_sum(self):
        cb = _fixture_cbom()
        s = CBOM.summarize(cb)
        self.assertEqual(s["total"], sum(i["tokens"] for i in cb["items"]))
        # and the buckets must reconcile to the total (no double-count, no leakage)
        self.assertEqual(s["total"], s["user_config"] + s["mcp"] + s["base"] + s["other"])

    def test_empty_cbom(self):
        s = CBOM.summarize(CBOM.make_cbom([]))
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["count"], 0)
        for k in ("user_config", "skills", "plugins", "hooks", "mcp", "base", "other"):
            self.assertEqual(s[k], 0)

    def test_malformed_items_do_not_raise(self):
        s = CBOM.summarize({"items": [None, 5, "str",
                                      {"kind": "skill"},                 # missing tokens -> 0
                                      {"kind": "skill", "tokens": "x"},  # non-int -> 0
                                      {"kind": "skill", "tokens": -7},   # negative -> 0
                                      {"kind": "skill", "tokens": 9}]})
        self.assertEqual(s["skills"], 9)
        self.assertEqual(s["count"], 4)               # the 4 dict items; None/int/str skipped

    def test_summarize_non_dict_is_safe(self):
        self.assertEqual(CBOM.summarize(None)["total"], 0)
        self.assertEqual(CBOM.summarize([])["total"], 0)

    def test_summary_line_no_throw_on_any_input(self):
        for junk in (None, [], "x", 7, {"items": "nope"}):
            line = CBOM.summary_line(junk)
            self.assertIsInstance(line, str)
            self.assertIn("CBOM", line)
        self.assertIn("total≈", CBOM.summary_line(_fixture_cbom()))


class TestEstimateTokens(unittest.TestCase):
    def test_ceil_chars_over_four(self):
        self.assertEqual(CBOM.estimate_tokens("abcd"), 1)
        self.assertEqual(CBOM.estimate_tokens("abcde"), 2)
        self.assertEqual(CBOM.estimate_tokens("a" * 400), 100)

    def test_empty_and_junk(self):
        self.assertEqual(CBOM.estimate_tokens(""), 0)
        self.assertEqual(CBOM.estimate_tokens(None), 0)
        self.assertEqual(CBOM.estimate_tokens(123), 0)
        self.assertEqual(CBOM.estimate_tokens([1, 2]), 0)

    def test_bytes(self):
        self.assertEqual(CBOM.estimate_tokens(b"abcdefgh"), 2)

    def test_estimate_file_tokens_missing_is_zero(self):
        self.assertEqual(CBOM.estimate_file_tokens("/no/such/file.txt"), (0, 0))

    def test_estimate_file_tokens_real_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write("x" * 40)
            p = fh.name
        try:
            tok, nbytes = CBOM.estimate_file_tokens(p)
            self.assertEqual(nbytes, 40)
            self.assertEqual(tok, 10)
        finally:
            os.unlink(p)


class TestParse(unittest.TestCase):
    def test_roundtrip(self):
        cb = _fixture_cbom()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(cb, fh)
            p = fh.name
        try:
            loaded = CBOM.parse(p)
            self.assertEqual(CBOM.summarize(loaded)["total"], CBOM.summarize(cb)["total"])
            self.assertEqual(len(loaded["items"]), len(cb["items"]))
        finally:
            os.unlink(p)

    def test_missing_file_degrades_to_empty(self):
        cb = CBOM.parse("/nonexistent/dir/cbom.json")
        self.assertIsInstance(cb, dict)
        self.assertEqual(cb["items"], [])
        self.assertEqual(CBOM.summarize(cb)["total"], 0)

    def test_non_json_degrades_to_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("this is not json {{{")
            p = fh.name
        try:
            self.assertEqual(CBOM.parse(p)["items"], [])
        finally:
            os.unlink(p)

    def test_items_not_a_list_is_coerced(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"version": "0.1", "items": {"not": "a list"}}, fh)
            p = fh.name
        try:
            self.assertEqual(CBOM.parse(p)["items"], [])
        finally:
            os.unlink(p)


class TestHook(unittest.TestCase):
    def test_build_cbom_tags_session_metadata(self):
        payload = {"session_id": "s1", "hook_event_name": "SessionStart",
                   "source": "startup", "cwd": "/tmp"}
        cb = HOOK.build_cbom(payload, items=[CBOM.make_item("skill", "x", tokens=8)])
        self.assertEqual(cb["session"]["session_id"], "s1")
        self.assertEqual(cb["session"]["hook_event_name"], "SessionStart")
        self.assertEqual(CBOM.summarize(cb)["skills"], 8)
        self.assertTrue(cb["generated_at"])

    def test_build_cbom_no_payload_is_safe(self):
        cb = HOOK.build_cbom({}, items=[])
        self.assertEqual(cb["session"], {})
        self.assertEqual(CBOM.summarize(cb)["total"], 0)

    def test_write_then_parse_roundtrip(self):
        cb = HOOK.build_cbom({"session_id": "s2"},
                             items=[CBOM.make_item("mcp", "Notion", tokens=4000),
                                    CBOM.make_item("hook", "SessionStart:h", tokens=20)])
        d = tempfile.mkdtemp()
        out = os.path.join(d, "out.json")
        try:
            path = HOOK.write_cbom(cb, out)
            self.assertEqual(path, out)
            self.assertTrue(os.path.isfile(out))
            reloaded = CBOM.parse(out)
            s = CBOM.summarize(reloaded)
            self.assertEqual(s["mcp"], 4000)
            self.assertEqual(s["hooks"], 20)
            self.assertEqual(reloaded["session"]["session_id"], "s2")
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass
            os.rmdir(d)

    def test_scan_hooks_and_mcp_from_settings(self):
        items = []
        settings = {
            "hooks": {"SessionStart": [{"matcher": "*",
                                        "hooks": [{"type": "command", "command": "do-a-thing"}]}]},
            "mcpServers": {"Notion": {"command": "npx", "args": ["notion-mcp"]},
                           "Figma": {"url": "https://figma.example/mcp"}},
        }
        HOOK._scan_hooks(items, settings)
        HOOK._scan_mcp(items, settings)
        kinds = [i["kind"] for i in items]
        self.assertEqual(kinds.count("hook"), 1)
        self.assertEqual(kinds.count("mcp"), 2)
        # every scanned item carries a positive token estimate
        for it in items:
            self.assertGreater(it["tokens"], 0)

    def test_scan_helpers_tolerate_garbage(self):
        items = []
        HOOK._scan_hooks(items, {"hooks": "not a dict"})
        HOOK._scan_hooks(items, {})
        HOOK._scan_mcp(items, {"mcpServers": 5})
        HOOK._scan_mcp(items, {})
        self.assertEqual(items, [])

    def test_build_items_no_throw(self):
        # Pointed at a cwd with no CLAUDE.md / skills, this must return a list and never raise.
        d = tempfile.mkdtemp()
        try:
            items = HOOK.build_items({"cwd": d})
            self.assertIsInstance(items, list)
        finally:
            os.rmdir(d)

    def test_build_items_bad_cwd_falls_through(self):
        # A non-existent / non-string cwd must not raise; it falls back to a real dir.
        self.assertIsInstance(HOOK.build_items({"cwd": "/no/such/dir/xyz"}), list)
        self.assertIsInstance(HOOK.build_items({"cwd": 1234}), list)
        self.assertIsInstance(HOOK.build_items({}), list)

    def test_output_path_under_logos_cbom(self):
        p = HOOK.output_path()
        self.assertTrue(p.endswith(".json"))
        self.assertIn(os.path.join("logos", "cbom"), p)


if __name__ == "__main__":
    unittest.main()
