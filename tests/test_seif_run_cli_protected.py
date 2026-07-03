"""unittest: the CLI --protected flag wires through to seif_run(protected=...) — WIRING only, no editor/model.

Product finding (2026-07-02 audit, BUILD_LOG §7.2): the documented protected-set override for tasks that
legitimately add tests was Python-API-only; the CLI could not express it. Pins:

  - repeated --protected PATTERN flags reach seif_run as protected=tuple(patterns), in order;
  - with NO --protected, main() forwards NO protected kwarg, so the default PROTECTED tuple applies
    exactly as before;
  - main() exits 0 on accepted=True and 1 on accepted=False.

Hermetic: seif_run.seif_run is monkeypatched with a capturing fake; sys.argv is patched and restored.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "logos"))
import seif_run as SR  # noqa: E402

BASE_ARGV = ["seif_run.py", "--repo", "X", "--task", "t", "--test", "true", "--no-pr"]


class SeifRunCliProtectedTest(unittest.TestCase):
    def setUp(self):
        self._argv = sys.argv
        self._seif_run = SR.seif_run
        self.calls = []

        def fake(*args, **kwargs):
            self.calls.append((args, kwargs))
            return {"accepted": True}

        SR.seif_run = fake

    def tearDown(self):
        sys.argv = self._argv
        SR.seif_run = self._seif_run

    def test_protected_flags_forward_as_tuple_in_order(self):
        sys.argv = BASE_ARGV + ["--protected", "src/", "--protected", "*.lock"]
        with self.assertRaises(SystemExit) as cm:
            SR.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(len(self.calls), 1)
        _, kwargs = self.calls[0]
        self.assertEqual(kwargs["protected"], ("src/", "*.lock"))

    def test_no_flag_forwards_no_protected_kwarg(self):
        # absent flag -> no kwarg forwarded, so seif_run's default PROTECTED tuple applies unchanged
        sys.argv = list(BASE_ARGV)
        with self.assertRaises(SystemExit) as cm:
            SR.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(len(self.calls), 1)
        _, kwargs = self.calls[0]
        self.assertNotIn("protected", kwargs)

    def test_exit_code_1_on_rejected(self):
        def rejecting(*args, **kwargs):
            return {"accepted": False}

        SR.seif_run = rejecting
        sys.argv = list(BASE_ARGV)
        with self.assertRaises(SystemExit) as cm:
            SR.main()
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
