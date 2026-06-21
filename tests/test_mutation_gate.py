"""unittest for the Mutation Gate (v0.2 WP-C)."""
import ast, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import mutation_gate as MG

SRC = "def f(n):\n    if n > 0:\n        return n + 1\n    return n - 1\n"


class TestMutationGate(unittest.TestCase):
    def test_generates_valid_diverse_mutants(self):
        m = MG.generate_mutants(SRC)
        self.assertGreaterEqual(len(m), 3)
        self.assertTrue(all(ast.parse(x["source"]) for x in m))         # all valid python
        self.assertTrue(all(x["source"].strip() != SRC.strip() for x in m))  # no no-ops
        self.assertIn("boundary_or_equality", {x["family"] for x in m})

    def test_score_bounds(self):
        m = MG.generate_mutants(SRC)
        self.assertEqual(MG.mutation_score(m, lambda s: True)["score"], 1.0)
        self.assertEqual(MG.mutation_score(m, lambda s: False)["score"], 0.0)

    def test_executor_error_counts_as_not_killed(self):
        m = MG.generate_mutants(SRC)
        def boom(s): raise RuntimeError("x")
        r = MG.mutation_score(m, boom)
        self.assertEqual(r["killed"], 0)


if __name__ == "__main__":
    unittest.main()
