import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import capability_grant as CG
class T(unittest.TestCase):
    def g(self):
        return CG.mint_grant("g","agent:x","github",["list_issues","comment"],
                             read_scopes=["repo:a"], write_scopes=["repo:a:comments"],
                             expires_at="2999-01-01T00:00:00Z", risk_class="medium")
    def test_allow_read(self): self.assertEqual(CG.check(self.g(),"list_issues",scope="repo:a")[0], CG.ALLOW)
    def test_deny_ungranted(self): self.assertEqual(CG.check(self.g(),"merge")[0], CG.DENY)
    def test_deny_wrong_write_scope(self):
        self.assertEqual(CG.check(self.g(),"comment",scope="repo:b:comments",write=True)[0], CG.DENY)
    def test_deny_expired(self):
        self.assertEqual(CG.check(self.g(),"list_issues",now="2999-02-01T00:00:00Z")[0], CG.DENY)
    def test_protected_write_needs_approval(self):
        h=CG.mint_grant("h","a","stripe",["refund"],write_scopes=["live"],risk_class="protected")
        self.assertEqual(CG.check(h,"refund",scope="live",write=True)[0], CG.DENY)
        h["approval"]={"granted":True}
        self.assertEqual(CG.check(h,"refund",scope="live",write=True)[0], CG.ALLOW)
    def test_no_token_in_grant(self):
        self.assertNotIn("token", str(self.g()).lower())
if __name__=="__main__": unittest.main()
