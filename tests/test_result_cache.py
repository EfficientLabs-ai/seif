"""unittest for the SEIF exact-fingerprint result cache (logos/result_cache.py) and its opt-in wiring
into seif_run.

Pins the contract:
  (1) fingerprint is deterministic and EXACT — every field flips the key, no fuzzy collapse;
  (2) the cache works with NO Redis (file backend), storing + reusing patch + receipt;
  (3) an EXACT hit reuses the prior result and SKIPS the model call (seif_run._claude_edit not invoked);
  (4) any SINGLE field change is a MISS → the model runs;
  (5) opt-in: with the cache OFF (default), behaviour is byte-identical (no cache import/use).

Hermetic: file-backed cache pinned to a temp path (no ambient Redis), receipt/checkpoint ledgers pinned to
temp, and _claude_edit mocked (no real claude).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
import result_cache as RC  # noqa: E402
import seif_run as SR  # noqa: E402
import project_harness as H  # noqa: E402
import checkpoint as CP  # noqa: E402


CH = [["a.py", "h1"], ["b.py", "h2"]]
ARGS = ("fix the bug", "deadbeef00", "pytest", CH, "claude-opus-4-8", ["--strict-mcp-config"])


class FingerprintTest(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(RC.fingerprint(*ARGS), RC.fingerprint(*ARGS))

    def test_order_independent_over_same_file_set(self):
        a = RC.fingerprint("t", "c", "pytest", RC.changed_file_hashes(".", []), "m", None)
        b = RC.fingerprint("t", "c", "pytest", RC.changed_file_hashes(".", []), "m", None)
        self.assertEqual(a, b)
        # a list passed in two orderings, pre-sorted by the helper, yields one key
        s1 = sorted([["b.py", "h2"], ["a.py", "h1"]])
        s2 = sorted([["a.py", "h1"], ["b.py", "h2"]])
        self.assertEqual(RC.fingerprint("t", "c", "pytest", s1, "m", None),
                         RC.fingerprint("t", "c", "pytest", s2, "m", None))

    def test_every_field_flips_the_key(self):
        fp = RC.fingerprint(*ARGS)
        self.assertNotEqual(fp, RC.fingerprint("fix the BUG", *ARGS[1:]))           # task
        self.assertNotEqual(fp, RC.fingerprint(ARGS[0], "OTHER", *ARGS[2:]))        # base_commit
        self.assertNotEqual(fp, RC.fingerprint(*ARGS[:2], "go test", *ARGS[3:]))    # test_cmd
        self.assertNotEqual(fp, RC.fingerprint(*ARGS[:3],
                                               [["a.py", "DIFF"], ["b.py", "h2"]], *ARGS[4:]))  # file hash
        self.assertNotEqual(fp, RC.fingerprint(*ARGS[:4], "claude-haiku", ARGS[5]))  # model
        self.assertNotEqual(fp, RC.fingerprint(*ARGS[:5], ["--other"]))             # lean_flags

    def test_none_lean_flags_distinct_from_empty_list(self):
        self.assertNotEqual(RC.fingerprint(*ARGS[:5], None), RC.fingerprint(*ARGS[:5], []))


class FileHashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-rc-hash-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_content_change_changes_hash_editback_is_stable(self):
        p = os.path.join(self.tmp, "f.py")
        open(p, "w").write("print(1)\n")
        h1 = RC.hash_file(p)
        open(p, "w").write("print(2)\n")
        h2 = RC.hash_file(p)
        self.assertNotEqual(h1, h2)
        open(p, "w").write("print(1)\n")
        self.assertEqual(RC.hash_file(p), h1)         # identical bytes → identical hash

    def test_missing_file_hashes_to_none(self):
        self.assertIsNone(RC.hash_file(os.path.join(self.tmp, "nope.py")))

    def test_changed_file_hashes_sorted_and_relative(self):
        repo = self.tmp
        open(os.path.join(repo, "b.py"), "w").write("b\n")
        open(os.path.join(repo, "a.py"), "w").write("a\n")
        out = RC.changed_file_hashes(repo, ["b.py", "a.py"])
        self.assertEqual([row[0] for row in out], ["a.py", "b.py"])   # sorted by path
        self.assertTrue(all(row[1] for row in out))                   # both hashed


class FileBackendCacheTest(unittest.TestCase):
    """Cache works with NO Redis — pinned to a temp file path (a non-empty path forces the file backend)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-rc-cache-")
        self.path = os.path.join(self.tmp, "cache.json")
        self.rc = RC.ResultCache(path=self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_backend_is_file_without_redis(self):
        self.assertEqual(self.rc.backend, "file")

    def test_cold_miss_then_exact_hit_reuses_patch_and_receipt(self):
        self.assertIsNone(self.rc.lookup(*ARGS))     # cold
        self.rc.store(*ARGS, patch="DIFF-BODY", receipt={"h": "rcpt1", "outcome": "pass"},
                      extra={"branch": "seif/x"})
        hit = self.rc.lookup(*ARGS)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["patch"], "DIFF-BODY")
        self.assertEqual(hit["receipt"]["h"], "rcpt1")
        self.assertEqual(hit["branch"], "seif/x")

    def test_any_single_field_change_misses(self):
        self.rc.store(*ARGS, patch="P", receipt={"h": "r"})
        self.assertIsNone(self.rc.lookup("fix the BUG", *ARGS[1:]))           # task
        self.assertIsNone(self.rc.lookup(ARGS[0], "OTHER", *ARGS[2:]))        # base_commit
        self.assertIsNone(self.rc.lookup(*ARGS[:2], "go test", *ARGS[3:]))    # test_cmd
        self.assertIsNone(self.rc.lookup(*ARGS[:3],
                                         [["a.py", "DIFF"], ["b.py", "h2"]], *ARGS[4:]))  # file hash
        self.assertIsNone(self.rc.lookup(*ARGS[:4], "claude-haiku", ARGS[5]))  # model
        self.assertIsNone(self.rc.lookup(*ARGS[:5], []))                      # lean_flags
        self.assertIsNotNone(self.rc.lookup(*ARGS))                          # the exact key still hits

    def test_invalidate_drops_entry(self):
        self.rc.store(*ARGS, patch="P", receipt={"h": "r"})
        self.rc.invalidate(*ARGS)
        self.assertIsNone(self.rc.lookup(*ARGS))

    def test_persists_across_instances_file_backend(self):
        self.rc.store(*ARGS, patch="P2", receipt={"h": "r2"})
        rc2 = RC.ResultCache(path=self.path)
        self.assertEqual(rc2.lookup(*ARGS)["patch"], "P2")

    def test_ttl_expiry_on_read(self):
        self.rc.store(*ARGS, patch="P", receipt={"h": "r"}, ttl=-1)   # already expired
        self.assertIsNone(self.rc.lookup(*ARGS))                      # expiry enforced on read


class SeifRunWiringTest(unittest.TestCase):
    """The opt-in cache wired into seif_run: a hit SKIPS the model; off-by-default changes nothing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t-rc-wire-")
        self._h, self._l, self._f = H.RECEIPTS, CP.LEDGER, CP.FAILURES
        H.RECEIPTS = os.path.join(self.tmp, "rcpt.jsonl")
        CP.LEDGER = os.path.join(self.tmp, "cp.jsonl")
        CP.FAILURES = os.path.join(self.tmp, "fail.jsonl")
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        # a buggy source + a test that pins the fix; the honest editor below makes it pass
        open(os.path.join(self.repo, "calc.py"), "w").write("def add(a, b):\n    return a - b\n")
        open(os.path.join(self.repo, "test_calc.py"), "w").write(
            "import unittest\nfrom calc import add\n"
            "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n")
        g = lambda *a: subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True)
        g("add", "-A"); g("commit", "-qm", "base")
        self.cmd = f"{sys.executable} -m unittest -q test_calc"
        self.cache = RC.ResultCache(path=os.path.join(self.tmp, "cache.json"))
        self.assertEqual(self.cache.backend, "file")   # NO redis path

    def tearDown(self):
        H.RECEIPTS, CP.LEDGER, CP.FAILURES = self._h, self._l, self._f
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _honest_edit(self):
        calls = {"n": 0}

        def edit(wt, *a, **k):
            calls["n"] += 1
            open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
            return 0, SR.UM.empty()
        return edit, calls

    def test_off_by_default_does_not_invoke_cache(self):
        edit, calls = self._honest_edit()
        # OFF by default: result_cache=None + SEIF_RESULT_CACHE unset → the cache must never be constructed.
        # Patch RC.ResultCache so any attempt to build a cache on the default path is caught.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEIF_RESULT_CACHE", None)
            with mock.patch.object(RC, "ResultCache", side_effect=AssertionError("cache built on default path")) as ctor:
                with mock.patch.object(SR, "_claude_edit", side_effect=edit):
                    r = SR.seif_run(self.repo, "fix add", self.cmd, budget=1, base="HEAD", make_pr=False)
        self.assertTrue(r["accepted"])
        self.assertNotIn("cache_hit", r)               # no cache branch taken
        ctor.assert_not_called()                       # the cache class was never instantiated

    def test_first_run_misses_stores_then_hit_skips_model(self):
        edit, calls = self._honest_edit()
        # run 1: cold cache → model runs → verified → result stored
        with mock.patch.object(SR, "_claude_edit", side_effect=edit):
            r1 = SR.seif_run(self.repo, "fix add", self.cmd, budget=1, base="HEAD",
                             make_pr=False, result_cache=self.cache)
        self.assertTrue(r1["accepted"], r1)
        self.assertNotEqual(r1.get("reason"), "cache_hit")
        self.assertEqual(calls["n"], 1, "first run must call the model exactly once")
        H.discard(self.repo, r1["worktree"])

        # run 2: EXACT same inputs → cache HIT → model SKIPPED, prior patch+receipt reused
        edit2, calls2 = self._honest_edit()
        with mock.patch.object(SR, "_claude_edit", side_effect=edit2) as m2:
            r2 = SR.seif_run(self.repo, "fix add", self.cmd, budget=1, base="HEAD",
                             make_pr=False, result_cache=self.cache)
        self.assertTrue(r2["accepted"])
        self.assertEqual(r2["reason"], "cache_hit")
        self.assertTrue(r2.get("cache_hit"))
        m2.assert_not_called()                          # the model call was SKIPPED
        self.assertEqual(calls2["n"], 0)
        # the reused result is the stored patch + receipt from run 1
        self.assertEqual(r2["patch"], r1["patch"])
        self.assertEqual(r2["receipt"]["h"], r1["receipt"]["h"])

    def test_changed_task_misses_and_runs_model(self):
        edit, calls = self._honest_edit()
        with mock.patch.object(SR, "_claude_edit", side_effect=edit):
            r1 = SR.seif_run(self.repo, "fix add", self.cmd, budget=1, base="HEAD",
                             make_pr=False, result_cache=self.cache)
        self.assertTrue(r1["accepted"])
        H.discard(self.repo, r1["worktree"])
        # a DIFFERENT task string is a different fingerprint → MISS → model runs again
        edit2, calls2 = self._honest_edit()
        with mock.patch.object(SR, "_claude_edit", side_effect=edit2) as m2:
            r2 = SR.seif_run(self.repo, "fix subtraction", self.cmd, budget=1, base="HEAD",
                             make_pr=False, result_cache=self.cache)
        self.assertTrue(r2["accepted"])
        self.assertNotEqual(r2.get("reason"), "cache_hit")
        m2.assert_called()                              # model ran (a miss)
        self.assertEqual(calls2["n"], 1)
        H.discard(self.repo, r2["worktree"])

    def test_env_var_gate(self):
        # the explicit param wins over env; when param is None, the env var decides
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEIF_RESULT_CACHE", None)
            self.assertFalse(SR._result_cache_enabled(None))       # unset → off
        for truthy in ("1", "true", "yes", "on", "TRUE"):
            with mock.patch.dict(os.environ, {"SEIF_RESULT_CACHE": truthy}):
                self.assertTrue(SR._result_cache_enabled(None))
        for falsy in ("0", "false", "", "no"):
            with mock.patch.dict(os.environ, {"SEIF_RESULT_CACHE": falsy}):
                self.assertFalse(SR._result_cache_enabled(None))
        # explicit param overrides env entirely
        with mock.patch.dict(os.environ, {"SEIF_RESULT_CACHE": "1"}):
            self.assertFalse(SR._result_cache_enabled(False))
        with mock.patch.dict(os.environ, {"SEIF_RESULT_CACHE": "0"}):
            self.assertTrue(SR._result_cache_enabled(True))


if __name__ == "__main__":
    unittest.main()
