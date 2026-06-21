import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import assumption_graph as AG
class T(unittest.TestCase):
    def setUp(self):
        self.g=AG.AssumptionGraph()
        for n,t in [("A1","assumption"),("c","candidate"),("sk","skill"),("ca","cache_entry")]: self.g.add(n,t)
        self.g.link("c","DEPENDS_ON","A1"); self.g.link("sk","DERIVED_FROM","c"); self.g.link("ca","DEPENDS_ON","c")
    def test_cascade(self):
        a={x["id"]:x["new_status"] for x in self.g.invalidate("A1")}
        self.assertEqual(a["c"],"STALE"); self.assertEqual(a["sk"],"QUARANTINED"); self.assertEqual(a["ca"],"REVERIFY")
    def test_bad_edge(self):
        with self.assertRaises(ValueError): self.g.link("c","NOPE","A1")
if __name__=="__main__": unittest.main()
