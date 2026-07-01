"""unittest for the PR/commit formatter (logos/pr_format.py) — the SEIF GitHub house style."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import pr_format as PF


class PrBodyTest(unittest.TestCase):
    def _body(self, **kw):
        base = dict(
            summary="add the widget",
            changes=[("logos/x.py", "the widget"), ("tests/test_x.py", "its tests")],
            verification=[("Tests (`unittest`)", "138 pass (exit 0)", True), ("Integrity guard", "clean", True)],
        )
        base.update(kw)
        return PF.build_pr_body(**base)

    def test_has_banner_changes_and_verification_sections(self):
        b = self._body()
        self.assertIn("> **add the widget**", b)
        self.assertIn("`logos/x.py`", b)           # change row rendered as a table cell
        self.assertIn("- Tests (`unittest`): ✅ 138 pass (exit 0)", b)  # proof rendered as a FILLED BULLET

    # ---- Efficient Labs GitHub Operating Standard: the seven required H1 sections ----
    def test_emits_all_required_h1_sections(self):
        b = self._body()
        for section in ("# Summary", "# Problem", "# Solution", "# User / Project Impact",
                        "# Linked Context", "# Proof / Receipts", "# Merge Readiness"):
            self.assertIn(f"\n{section}\n", "\n" + b)  # exact H1 at line start

    def test_proof_section_has_filled_bullets(self):
        # the discipline gate counts "- x" bullets with content after any "Label:" prefix —
        # a table does NOT count, so proof MUST render as bullets.
        b = self._body()
        proof = b.split("# Proof / Receipts", 1)[1].split("# Merge Readiness", 1)[0]
        bullets = [ln for ln in proof.splitlines() if ln.strip().startswith("- ")]
        self.assertTrue(bullets, "proof section must contain bullets")
        self.assertTrue(any(ln.split(":", 1)[1].strip() for ln in bullets if ":" in ln),
                        "at least one bullet must have content beyond its label")

    def test_problem_and_impact_params_render(self):
        b = self._body(problem="the webhook could silently 200", impact="charged users always provision")
        self.assertIn("the webhook could silently 200", b)
        self.assertIn("charged users always provision", b)

    def test_empty_verification_cannot_satisfy_the_proof_gate(self):
        # the discipline gate counts any "- x" bullet as filled proof — with NO real
        # verification the section must contain no bullet at all, so the gate fails
        # closed instead of being satisfied by a placeholder
        b = self._body(verification=[])
        proof = b.split("# Proof / Receipts", 1)[1].split("# Merge Readiness", 1)[0]
        bullets = [ln for ln in proof.splitlines() if ln.strip().startswith(("- ", "* ", "+ "))]
        self.assertEqual(bullets, [], "no verification → no proof bullets (fail closed)")
        self.assertIn("no checks ran", proof)   # a human-readable non-bullet explanation remains

    def test_all_pass_shows_gate_verified_chip(self):
        self.assertIn(PF.chip(True, "gate verified"), self._body())

    def test_a_failed_check_flips_the_banner_chip(self):
        b = self._body(verification=[("Tests", "FAILED", False)])
        self.assertIn(PF.chip(False, "gate verified"), b)
        self.assertNotIn(PF.chip(True, "gate verified"), b)
        self.assertIn("⚠️ FAILED", b)              # failed row marked

    def test_codex_chip_and_row(self):
        b = self._body(codex={"approved": True, "verdict": "APPROVE"})
        self.assertIn("Codex review", b)            # added as a verification row
        self.assertIn(PF.chip(True, "Codex APPROVE"), b)

    def test_codex_request_changes_not_verified(self):
        b = self._body(codex={"approved": False, "verdict": "REQUEST_CHANGES"})
        self.assertIn("⚠️ REQUEST_CHANGES", b)
        self.assertNotIn(PF.chip(True, "gate verified"), b)  # an unapproved Codex sinks the gate chip

    def test_issue_link_and_founder_gate_footer(self):
        b = self._body(issue=25)
        self.assertIn("Closes #25", b)
        self.assertIn("never auto-merged — founder is the merge gate", b)
        self.assertIn(PF.PROVENANCE, b)

    def test_evidence_is_collapsible(self):
        b = self._body(evidence="Ran 138 tests\nOK")
        self.assertIn("<details>", b)
        self.assertIn("<summary>📋 Evidence</summary>", b)
        self.assertIn("Ran 138 tests", b)

    def test_no_evidence_no_details(self):
        self.assertNotIn("<details>", self._body())

    def test_non_autonomous_omits_gate_note(self):
        b = self._body(autonomous=False)
        self.assertNotIn("founder is the merge gate", b)

    # ---- markdown-safety: untrusted cell content must never break the table ----
    def test_pipe_in_cells_is_escaped(self):
        # a `|` in a filename or purpose must be escaped, not a new column; proof bullets
        # reuse the same escaping so odd characters render inertly there too
        b = self._body(
            changes=[("logos/a|b.py", "does x | y")],
            verification=[("Tests | unit", "138 pass | exit 0", True)])
        self.assertIn(r"a\|b.py", b)
        self.assertIn(r"does x \| y", b)
        self.assertIn(r"Tests \| unit", b)
        self.assertIn(r"138 pass \| exit 0", b)
        self.assertNotIn("a|b.py", b)          # the raw, un-escaped pipe must not survive

    def test_newline_in_cell_is_collapsed(self):
        # a newline inside a cell must be flattened to a space — it must NOT inject a fake table row
        b = self._body(
            changes=[("logos/x.py", "line1\nline2")],
            verification=[("Tests", "ok\nstill ok", True)])
        for line in b.splitlines():
            # no cell value leaks onto its own line — a newline must not inject a fake table row
            self.assertNotEqual(line.strip(), "line2")
            self.assertNotEqual(line.strip(), "still ok")
        self.assertIn("line1 line2", b)
        self.assertIn("ok still ok", b)

    def test_malformed_short_verification_tuple_does_not_crash(self):
        # a short / bare-string verification entry must render, not raise (resilient _vrow)
        b = self._body(verification=[("Tests only",), "just a string", ("Check", "result", True)])
        self.assertIn("Tests only", b)
        self.assertIn("just a string", b)
        self.assertIn("Check", b)
        # a row with no explicit ok flag is treated as not-ok → it sinks the gate-verified chip
        self.assertIn(PF.chip(False, "gate verified"), b)

    def test_malformed_short_changes_entry_does_not_crash(self):
        # a bare string or single-item changes entry must render, not raise (resilient _crow)
        b = self._body(changes=["logos/lonely.py", ("logos/x.py",), ("logos/y.py", "purpose")])
        self.assertIn("`logos/lonely.py`", b)
        self.assertIn("`logos/x.py`", b)
        self.assertIn("purpose", b)

    def test_summary_newline_cannot_break_the_banner(self):
        # a newline / heading-like summary must collapse to one inline banner line, not escape it
        b = self._body(summary="add widget\n# INJECTED HEADING\nmore")
        self.assertIn("> **add widget # INJECTED HEADING more**", b)
        for line in b.splitlines():
            self.assertNotEqual(line.strip(), "# INJECTED HEADING")   # never its own heading line

    def test_evidence_backticks_cannot_escape_the_code_block(self):
        # evidence containing a ``` run must be wrapped in a LONGER fence so it can't terminate early
        b = self._body(evidence="before\n```\nfake heading after fence\n```\nafter")
        self.assertIn("fake heading after fence", b)
        # the block is opened and closed by exactly two 4-backtick fence lines (the inner ``` is content)
        fence_lines = [ln for ln in b.splitlines() if ln.strip() == "````"]
        self.assertEqual(len(fence_lines), 2)


class CommitTest(unittest.TestCase):
    def test_conventional_with_scope_bullets_trailers(self):
        m = PF.build_commit("feat", "add the widget", scope="loop",
                            bullets=["does X", "tested via Y"],
                            trailers=["Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"])
        self.assertTrue(m.startswith("feat(loop): add the widget\n\n- does X\n- tested via Y\n\nCo-Authored-By:"))

    def test_no_scope(self):
        self.assertTrue(PF.build_commit("fix", "patch it").startswith("fix: patch it"))

    def test_unknown_type_falls_back_to_chore(self):
        self.assertTrue(PF.build_commit("banana", "x").startswith("chore: x"))


class IssueRefTest(unittest.TestCase):
    def test_extracts_first_issue(self):
        self.assertEqual(PF.issue_ref("Implement issue #23 (delta plan); see #99"), 23)

    def test_none_when_absent(self):
        self.assertIsNone(PF.issue_ref("no issue here"))


if __name__ == "__main__":
    unittest.main()
