import unittest

from memory.continuity_contract import REQUIRED_METHODS, TS_INTERFACE, conforms


class CompleteAdapter:
    def write_event(self, event): pass
    def read_context(self, query): pass
    def checkpoint(self, scope): pass
    def attach_evidence(self, evidence): pass
    def promote_to_graph(self, event_ids): pass


class IncompleteAdapter:
    def write_event(self, event): pass


class TestContinuityContract(unittest.TestCase):
    def test_complete_adapter_conforms(self):
        ok, missing = conforms(CompleteAdapter())
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_incomplete_adapter_lists_missing_methods(self):
        ok, missing = conforms(IncompleteAdapter())
        self.assertFalse(ok)
        self.assertEqual(missing, REQUIRED_METHODS[1:])

    def test_typescript_interface_names_are_published(self):
        self.assertIn("writeEvent", TS_INTERFACE)
        self.assertIn("promoteToGraph", TS_INTERFACE)


if __name__ == "__main__":
    unittest.main()
