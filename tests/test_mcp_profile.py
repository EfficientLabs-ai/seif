import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import mcp_profile as MP, capability_grant as CG
def _g():
    return CG.mint_grant("gX","agent:w","tools",[CG.action_spec("run_test"),CG.action_spec("apply_patch",write=True)],
                         expires_at="2999-01-01T00:00:00Z", task_id="task1")
class T(unittest.TestCase):
    def test_allow(self): self.assertEqual(MP.intercept(MP.make_envelope("agent:w","run_test","gX","task1"),_g())[0], MP.ALLOW)
    def test_ungranted_tool(self): self.assertEqual(MP.intercept(MP.make_envelope("agent:w","request_candidate","gX","task1"),_g())[0], MP.DENY)
    def test_capability_mismatch(self): self.assertEqual(MP.intercept(MP.make_envelope("agent:w","run_test","NOPE","task1"),_g())[0], MP.DENY)
    def test_task_mismatch(self): self.assertEqual(MP.intercept(MP.make_envelope("agent:w","run_test","gX","other"),_g())[0], MP.DENY)
    def test_telemetry_typing(self):
        self.assertTrue(MP.validate_telemetry("test_result",{"outcome":"pass","exit_code":0}))
        with self.assertRaises(MP.ProfileError): MP.validate_telemetry("test_result",{"outcome":"pass"})
if __name__=="__main__": unittest.main()
