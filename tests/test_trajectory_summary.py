import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import trajectory_summary as TS
class T(unittest.TestCase):
    def test_reusable(self):
        s=TS.build_summary("a","t","h","gate_complete",reusable_lesson_candidate="x"); self.assertTrue(TS.is_reusable(s))
    def test_not_reusable_when_prohibited(self):
        s=TS.build_summary("a","t","h","gate_complete",reusable_lesson_candidate="x",prohibited_reuse_reasons=["overfit"])
        self.assertFalse(TS.is_reusable(s))
    def test_bad_termination(self):
        with self.assertRaises(TS.SummaryError): TS.build_summary("a","t","h","nope")
if __name__=="__main__": unittest.main()
