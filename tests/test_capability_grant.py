import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import capability_grant as CG
class T(unittest.TestCase):
    def g(self):
        return CG.mint_grant("g","agent:x","github",
            [CG.action_spec("list_issues",write=False,scope="repo:a"),
             CG.action_spec("comment",write=True,scope="repo:a:comments")],
            expires_at="2999-01-01T00:00:00Z", risk_class="medium")
    def test_allow_granted(self): self.assertEqual(CG.check(self.g(),"list_issues")[0], CG.ALLOW)
    def test_deny_ungranted(self): self.assertEqual(CG.check(self.g(),"merge")[0], CG.DENY)
    def test_deny_expired(self): self.assertEqual(CG.check(self.g(),"list_issues",now="2999-02-01T00:00:00Z")[0], CG.DENY)
    def test_protected_write_strict_approval(self):
        h=CG.mint_grant("h","a","stripe",[CG.action_spec("refund",write=True,risk="protected")],expires_at="2999-01-01T00:00:00Z")
        self.assertEqual(CG.check(h,"refund")[0], CG.DENY)
        h["approval"]={"granted":"yes"}; self.assertEqual(CG.check(h,"refund")[0], CG.DENY)  # not strictly True
        h["approval"]={"granted":True}; self.assertEqual(CG.check(h,"refund")[0], CG.ALLOW)
    def test_missing_expiry_rejected(self):
        with self.assertRaises(CG.GrantError): CG.mint_grant("x","a","slack",[],expires_at=None)
    def test_unparseable_expiry_fails_closed(self):
        b=CG.mint_grant("b","a","slack",[CG.action_spec("post")],expires_at="2999-01-01T00:00:00Z"); b["expires_at"]="nope"
        self.assertEqual(CG.check(b,"post")[0], CG.DENY)
    def test_no_token_in_grant(self): self.assertNotIn("token", str(self.g()).lower())
if __name__=="__main__": unittest.main()
