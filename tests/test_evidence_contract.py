"""unittest wrapper for the Evidence Contract (v0.2 WP-A) — dependency-free."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import evidence_contract as EC


class TestEvidenceContract(unittest.TestCase):
    def _c(self):
        o = EC.make_obligation("O1", "behavior X holds", "issue", "effect",
                               ["candidate_blind_test"], "rej", "unk")
        return EC.build_contract("t1", "obj", [o], repository="r", base_commit="c")

    def test_build_validates_and_freezes(self):
        c = self._c()
        self.assertTrue(EC.validate(c))
        self.assertTrue(EC.verify_unmutated(c))
        self.assertTrue(c["contract_hash"])

    def test_tamper_detected(self):
        c = self._c()
        c["objective"] = "changed after freeze"
        self.assertFalse(EC.verify_unmutated(c))

    def test_reward_hacking_protected_paths(self):
        c = self._c()
        self.assertTrue(any(p.startswith("tests") for p in c["protected_paths"]))
        self.assertIn("swebench/", c["protected_paths"])

    def test_missing_field_rejected(self):
        c = self._c(); del c["mandatory_obligations"]
        with self.assertRaises(EC.ContractError):
            EC.validate(c)

    def test_empty_evidence_rejected(self):
        with self.assertRaises(EC.ContractError):
            EC.make_obligation("Ox", "r", "issue", "e", [], "rej", "unk")


if __name__ == "__main__":
    unittest.main()
