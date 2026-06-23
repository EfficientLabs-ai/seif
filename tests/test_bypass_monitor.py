"""unittest for the gate-bypass-sentinel detector (seif issue #21)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import bypass_monitor as BM


class TestBypassMonitor(unittest.TestCase):
    def test_outside_clean_room_bypass_high(self):
        r = BM.classify_action({"tool": "Write", "path": ".seif-gate-off", "in_clean_room": False})
        self.assertEqual(r["severity"], "high")
        self.assertEqual(r["vector"], "gate_bypass_sentinel")
        self.assertTrue(r["reason"])

    def test_normal_write_none(self):
        r = BM.classify_action({"tool": "Write", "path": "logos/some_module.py", "in_clean_room": False})
        self.assertEqual(r["severity"], "none")

    def test_clean_room_internal_none(self):
        r = BM.classify_action({"tool": "Write", "path": ".seif-gate-off", "in_clean_room": True})
        self.assertEqual(r["severity"], "none")

    def test_case_variant_high(self):
        r = BM.classify_action({"tool": "Edit", "path": ".SEIF-GATE-OFF", "in_clean_room": False})
        self.assertEqual(r["severity"], "high")
        self.assertEqual(r["vector"], "gate_bypass_sentinel")

    def test_subdir_variant_high(self):
        r = BM.classify_action({"tool": "Write", "path": "sub/dir/.seif-gate-off", "in_clean_room": False})
        self.assertEqual(r["severity"], "high")
        self.assertEqual(r["vector"], "gate_bypass_sentinel")

    def test_home_tilde_variant_high(self):
        r = BM.classify_action({"tool": "Write", "path": "~/.seif-gate-off", "in_clean_room": False})
        self.assertEqual(r["severity"], "high")
        self.assertEqual(r["vector"], "gate_bypass_sentinel")

    def test_subdir_clean_room_internal_none(self):
        r = BM.classify_action({"tool": "Write", "path": "sub/dir/.seif-gate-off", "in_clean_room": True})
        self.assertEqual(r["severity"], "none")

    def test_non_write_tool_on_sentinel_none(self):
        # a READ/list/delete of a .seif-gate-off path is NOT a gate-disable — must be benign (Codex MED fix)
        for tool in ("Read", "Glob", "Grep", "LS"):
            r = BM.classify_action({"tool": tool, "path": "~/.claude/.seif-gate-off", "in_clean_room": False})
            self.assertEqual(r["severity"], "none", f"{tool} on a sentinel must not flag")

    def test_bash_write_flag_high(self):
        # Bash is ambiguous from path alone; an explicit writes=True (caller detected a create/write) flags it
        r = BM.classify_action({"tool": "Bash", "path": "~/.claude/.seif-gate-off",
                                "in_clean_room": False, "writes": True})
        self.assertEqual(r["severity"], "high")
        # a Bash action that does NOT write (e.g. cat) is benign
        r2 = BM.classify_action({"tool": "Bash", "path": "~/.claude/.seif-gate-off", "in_clean_room": False})
        self.assertEqual(r2["severity"], "none")


if __name__ == "__main__":
    unittest.main()
