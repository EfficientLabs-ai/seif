"""unittest for the SEIF L4 Checkpoint Engine (verified, proof-gated, hash-chained system states)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import checkpoint as CP  # noqa: E402


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-cp-")
        CP.LEDGER = os.path.join(self.tmp, "cp.jsonl")
        CP.FAILURES = os.path.join(self.tmp, "fail.jsonl")
        self.repo = os.path.join(self.tmp, "repo")
        self._g = lambda *a: subprocess.run(
            ["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
            check=True, capture_output=True)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        open(os.path.join(self.repo, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
        self._g("add", "-A"); self._g("commit", "-qm", "v1")
        self.c1 = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()

    def _commit(self, body, msg):
        open(os.path.join(self.repo, "calc.py"), "w").write(body)
        self._g("add", "-A"); self._g("commit", "-qm", msg)
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()

    # ---- proof-gating: a checkpoint is known-good by construction ----
    def test_create_requires_passing_proof(self):
        for bad in (None, {}, {"outcome": "fail", "receipt": "r"}, {"outcome": "pass"}, {"receipt": "r"}):
            with self.assertRaises(CP.CheckpointError):
                CP.create(self.repo, "x", commit=self.c1, proof=bad)

    def test_create_requires_commit(self):
        with self.assertRaises(CP.CheckpointError):
            CP.create(self.repo, "x", commit="", proof={"outcome": "pass", "receipt": "r"})

    def test_create_and_last_healthy(self):
        cp = CP.create(self.repo, "add works", commit=self.c1,
                       proof={"outcome": "pass", "receipt": "r1", "exit_code": 0},
                       context={"task": "impl add", "files_changed": ["calc.py"]})
        self.assertEqual(CP.last_healthy(self.repo)["id"], cp["id"])
        self.assertEqual(cp["context"]["files_changed"], ["calc.py"])

    # ---- lineage + parent chaining ----
    def test_lineage_order_and_parent(self):
        cp1 = CP.create(self.repo, "v1", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        c2 = self._commit("def add(a, b):\n    return a + b\ndef sub(a, b):\n    return a - b\n", "v2")
        cp2 = CP.create(self.repo, "v2", commit=c2, proof={"outcome": "pass", "receipt": "r2"},
                        parent=cp1["id"])
        self.assertEqual([c["id"] for c in CP.lineage(self.repo)], [cp1["id"], cp2["id"]])
        self.assertEqual(cp2["parent"], cp1["id"])
        self.assertEqual(CP.last_healthy(self.repo)["id"], cp2["id"])

    def test_unhealthy_not_rollback_target(self):
        cp1 = CP.create(self.repo, "good", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        CP.create(self.repo, "wip", commit=self.c1, proof={"outcome": "pass", "receipt": "r2"}, healthy=False)
        self.assertEqual(CP.last_healthy(self.repo)["id"], cp1["id"])

    def test_repo_isolation(self):
        CP.create(self.repo, "a", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.assertEqual(CP.lineage(other), [])
        self.assertIsNone(CP.last_healthy(other))

    # ---- restore materializes the verified commit ----
    def test_restore_materializes_commit(self):
        cp1 = CP.create(self.repo, "v1", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        self._commit("def add(a, b):\n    return a + b\ndef sub(a, b):\n    return a - b\n", "v2")
        dest = os.path.join(self.tmp, "restored")
        CP.restore(self.repo, cp1["id"], dest)
        body = open(os.path.join(dest, "calc.py")).read()
        self.assertIn("def add", body)
        self.assertNotIn("def sub", body)   # restored the v1 state, not the latest

    def test_restore_unknown_raises(self):
        with self.assertRaises(CP.CheckpointError):
            CP.restore(self.repo, "nope", os.path.join(self.tmp, "x"))

    # ---- ASRS failure forensics ----
    def test_record_failure_defaults_rollback_to_last_healthy(self):
        cp = CP.create(self.repo, "good", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        f = CP.record_failure(self.repo, broken_patch_sha="deadbeef", failure_reason="type error",
                              affected_modules=["calc.py"], triggered_by="add multiply")
        self.assertEqual(f["rollback_to"], cp["id"])
        self.assertEqual(f["failure_reason"], "type error")
        self.assertEqual(f["affected_modules"], ["calc.py"])

    def test_record_failure_no_healthy_yet(self):
        f = CP.record_failure(self.repo, broken_patch_sha="x", failure_reason="boom")
        self.assertIsNone(f["rollback_to"])

    # ---- hash-chain integrity ----
    def test_chain_verifies_and_detects_tamper(self):
        CP.create(self.repo, "v1", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        CP.create(self.repo, "v1b", commit=self.c1, proof={"outcome": "pass", "receipt": "r2"})
        self.assertTrue(CP.verify_chain(CP.LEDGER)[0])
        lines = open(CP.LEDGER).read().splitlines()
        rec = json.loads(lines[0]); rec["label"] = "TAMPERED"
        lines[0] = json.dumps(rec); open(CP.LEDGER, "w").write("\n".join(lines) + "\n")
        self.assertFalse(CP.verify_chain(CP.LEDGER)[0])

    def test_read_ignores_non_dict_lines(self):
        # valid JSON scalars/arrays in the registry must be skipped, not crash dict-assuming callers
        CP.create(self.repo, "v1", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        with open(CP.LEDGER, "a") as fh:
            fh.write("null\n[]\n123\n\"str\"\n")
        self.assertEqual(len(CP.lineage(self.repo)), 1)        # non-dicts ignored
        self.assertIsNotNone(CP.last_healthy(self.repo))
        # a new create still chains cleanly over the junk
        CP.create(self.repo, "v2", commit=self.c1, proof={"outcome": "pass", "receipt": "r2"})
        self.assertEqual(len(CP.lineage(self.repo)), 2)

    def test_ids_unique_same_commit_label(self):
        a = CP.create(self.repo, "same", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        b = CP.create(self.repo, "same", commit=self.c1, proof={"outcome": "pass", "receipt": "r2"})
        self.assertNotEqual(a["id"], b["id"], "nonce must make ids unique even for same repo/commit/label")

    def test_non_sha_commit_rejected(self):
        with self.assertRaises(CP.CheckpointError):
            CP.create(self.repo, "x", commit="not-a-sha", proof={"outcome": "pass", "receipt": "r"})

    def test_read_tolerates_torn_line(self):
        CP.create(self.repo, "v1", commit=self.c1, proof={"outcome": "pass", "receipt": "r1"})
        with open(CP.LEDGER, "a") as fh:
            fh.write('{"torn":')   # truncated final line
        self.assertEqual(len(CP.lineage(self.repo)), 1)   # ignored, no crash


if __name__ == "__main__":
    unittest.main()
