"""unittest for the Tripartite Memory contract — the seif facade conforms; incomplete impls are flagged."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import contract as C  # noqa: E402
from tripartite import EpisodicMemory, Memory, WorkingMemory  # noqa: E402


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-contract-")
        self.mem = Memory()
        self.mem.working = WorkingMemory(path=os.path.join(self.tmp, "w.json"))
        self.mem.episodic = EpisodicMemory(path=os.path.join(self.tmp, "ep.jsonl"))

    def test_seif_memory_conforms(self):
        g = self.mem.graph(os.path.join(self.tmp, "norepo"))   # an L3 view
        ok, missing = C.conforms(self.mem, semantic=g)
        self.assertTrue(ok, f"seif Memory must satisfy the contract; missing={missing}")
        self.assertEqual(missing, [])

    def test_contract_has_all_four_layers(self):
        self.assertEqual(set(C.CONTRACT), {"L1_working", "L2_episodic", "L3_semantic", "facade"})
        for v in C.CONTRACT.values():
            self.assertTrue(v and all(isinstance(m, str) for m in v))

    def test_incomplete_impl_flagged(self):
        class Half:
            def remember(self):
                pass
        ok, missing = C.conforms(Half())
        self.assertFalse(ok)
        self.assertTrue(any("facade.recall" in m for m in missing))     # missing facade method reported
        self.assertTrue(any("L1" in m for m in missing))                # missing L1 layer reported

    def test_l1_backend_attribute_required(self):
        class NoBackend:                       # has the methods but no `backend` attribute
            def set(self, *a, **k): pass
            def get(self, *a, **k): pass
            def delete(self, *a, **k): pass
            def keys(self, *a, **k): pass
        ok, missing = C.conforms(self.mem, working=NoBackend())
        self.assertFalse(ok)
        self.assertIn("L1.backend (attribute)", missing)

    def test_l3_checked_only_when_supplied(self):
        # without a semantic view, L3 methods aren't checked, but the facade's graph() still is
        ok, missing = C.conforms(self.mem)
        self.assertTrue(ok, missing)           # facade.graph present → conforms even without an L3 view
        # a broken L3 view is flagged when supplied
        ok2, missing2 = C.conforms(self.mem, semantic=object())
        self.assertFalse(ok2)
        self.assertTrue(any("L3." in m for m in missing2))

    def test_l3_available_attribute_required(self):
        # an L3 view with the methods but NO `available` attribute must be flagged
        class NoAvailable:
            def impact(self, *a, **k): pass
            def dependencies(self, *a, **k): pass
            def path(self, *a, **k): pass
        ok, missing = C.conforms(self.mem, semantic=NoAvailable())
        self.assertFalse(ok)
        self.assertIn("L3.available (attribute)", missing)


if __name__ == "__main__":
    unittest.main()
