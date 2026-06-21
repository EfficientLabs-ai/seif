import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import test_architect as TA
class T(unittest.TestCase):
    def test_blind_context_ok(self):
        self.assertTrue(TA.assert_blind({"task_id":"t","issue":"i","repo_view":["a.py"]}))
    def test_rejects_candidate(self):
        with self.assertRaises(TA.BlindnessError): TA.assert_blind({"task_id":"t","issue":"i","candidate_patch":"d"})
    def test_rejects_gold(self):
        with self.assertRaises(TA.BlindnessError): TA.assert_blind({"task_id":"t","issue":"i","gold":"x"})
    def test_rejects_nested_hidden(self):
        with self.assertRaises(TA.BlindnessError): TA.assert_blind({"task_id":"t","issue":"i","repo_view":[{"test_patch":"h"}]})
    def test_rejects_extra_key(self):
        with self.assertRaises(TA.BlindnessError): TA.assert_blind({"task_id":"t","issue":"i","sneaky":1})
    def test_plan_frozen_tamper_evident(self):
        ctx={"task_id":"t","issue":"i"}
        p=TA.author_tests(ctx, lambda c:{"tests":[{"id":"T1","kind":"acceptance"}]})
        self.assertTrue(TA.verify_plan_unmutated(p))
        p["tests"][0]["kind"]="negative"
        self.assertFalse(TA.verify_plan_unmutated(p))
if __name__=="__main__": unittest.main()
