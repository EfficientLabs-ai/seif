#!/usr/bin/env python3
"""/seif — the driver that runs the SEIF stack on YOUR repo. Generate → evidence-verify against your
own tests → iterate on failure → land on a branch (PR if a remote exists), NEVER main, with a receipt.

This is the embodiment of the whole thesis for real work: the model proposes; the project's own test
suite (exit code) disposes; failures roll back; success is provable. You stay at the merge gate.

Usage:
  python3 logos/seif_run.py --repo /home/neo/StratosAgent --test "npm test" --task "Fix X. Don't edit tests."
  flags: --budget N (default 3) · --base REF (default HEAD) · --timeout S (default 600) · --no-pr
"""
import argparse
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_harness as H   # noqa: E402
import integrity_guard as IG  # noqa: E402
import checkpoint as CP       # noqa: E402  (L4: register verified states / record failure forensics)

CLAUDE = "/home/neo/.local/bin/claude"

# Protected surface for PROJECT-mode reward-hacking defense: a candidate must never make tests "pass"
# by editing the tests, the CI, or the test runner itself. Source-only fixes. (Callers can override for
# a task that legitimately adds tests — but the autonomous default protects the grader.)
PROTECTED = (
    "test/", "tests/", "spec/", "specs/", "__tests__/", "e2e/",
    "test_*.py", "*_test.py", "*.test.js", "*.test.ts", "*.test.tsx", "*.test.jsx",
    "*.test.mjs", "*.spec.js", "*.spec.ts", "*.spec.tsx", "*.spec.py", "conftest.py",
    ".github/", "jest.config.*", "vitest.config.*", "pytest.ini", "tox.ini", "playwright.config.*",
    "run-tests.*", "run_tests.*",
)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "task"


def _claude_edit(worktree, task, feedback, first, timeout):
    if first:
        prompt = (f"You are making a focused change in this repository (cwd).\n\nTASK:\n{task}\n\n"
                  "Edit the SOURCE to accomplish it and make the project's tests pass. Do NOT edit tests. "
                  "Make the change and stop.")
    else:
        prompt = (f"You are fixing a change in this repository (cwd).\n\nTASK:\n{task}\n\n"
                  f"The project's tests are STILL FAILING:\n{feedback[:4500]}\n\n"
                  "Fix the SOURCE so the tests pass. Do NOT edit tests. Make the change and stop.")
    try:
        p = subprocess.run([CLAUDE, "-p", "--permission-mode", "acceptEdits", prompt],
                           cwd=worktree, timeout=timeout, capture_output=True, text=True)
        return p.returncode
    except subprocess.TimeoutExpired:
        return None


def _has_remote(repo):
    r = subprocess.run(["git", "-C", repo, "remote"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _repo_slug(repo):
    """OWNER/REPO from the origin remote URL (gh -R wants this, not a local path)."""
    url = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def _resolve_base(repo, base):
    """Resolve the clean-room base ref. 'last-healthy' → the last HEALTHY L4 checkpoint's commit (or
    'HEAD' if none yet); any other value (incl. the default 'HEAD') is returned unchanged. Defensive: a
    missing/None/malformed checkpoint record falls back to 'HEAD' and never crashes the run."""
    if base != "last-healthy":
        return base
    try:
        last = CP.last_healthy(repo)
        commit = last.get("commit") if isinstance(last, dict) else None
    except Exception:  # noqa: BLE001 — base resolution must never break the gate; degrade to HEAD
        commit = None
    return commit or "HEAD"


def seif_run(repo, task, test_cmd, budget=3, base="HEAD", timeout=600, make_pr=True, protected=PROTECTED):
    repo = os.path.abspath(repo)
    base = _resolve_base(repo, base)
    wt = H.checkpoint(repo, base)
    feedback, passed, result, patch, integrity = "", False, None, "", None
    print(f"[/seif] repo={os.path.basename(repo)} test='{test_cmd}' budget={budget}\n[/seif] clean room: {wt}")
    try:
        def _stage_diff():
            subprocess.run(["git", "-C", wt, "add", "-A"], capture_output=True)
            return subprocess.run(["git", "-C", wt, "diff", "--cached"], capture_output=True, text=True).stdout

        for step in range(1, budget + 1):
            integrity = None                          # never carry a prior step's verdict forward
            rc = _claude_edit(wt, task, feedback, step == 1, timeout)
            patch = _stage_diff()
            if not patch.strip():
                print(f"[/seif] step {step}: agent made no change (rc={rc}) — stop")
                result = {"outcome": "no_change", "exit_code": None}
                break
            result = H.run_tests(wt, test_cmd, timeout=timeout)
            print(f"[/seif] step {step}: tests -> {result['outcome']} (exit {result['exit_code']}, {result['seconds']}s)")
            if result["outcome"] == "pass":
                # Re-snapshot AFTER tests: running the suite can touch tracked files, and we must
                # integrity-check (and later commit) EXACTLY what is graded — not the pre-test snapshot.
                patch = _stage_diff()
                clean, integrity = IG.is_clean(patch, protected)
                if clean:
                    passed = True
                    break
                # Tests pass BUT the candidate edited a protected surface (tests/CI/runner) = reward-hacking.
                # Reject this candidate; feed the violation back and let the remaining budget try a clean fix.
                violated = [h["file"] for h in integrity["hard"]]
                result["outcome"] = "integrity_violation"
                print(f"[/seif] step {step}: INTEGRITY VIOLATION — protected edits: {violated}")
                feedback = ("Tests passed BUT your change edited a PROTECTED path (tests, CI, or the test "
                            f"runner): {violated}. That is not allowed — fix the SOURCE only, never the "
                            "tests or test config. Make the source change that passes the EXISTING tests.")
                continue
            feedback = (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-4500:]
        rec = H._receipt(repo, task, test_cmd, result or {"outcome": "no_change", "exit_code": None}, patch)
        if not passed:
            H.discard(repo, wt)                                   # ATMS rollback — main untouched
            why = {"integrity_violation": "integrity_violation",
                   "no_change": "no_change"}.get((result or {}).get("outcome"), "tests")
            # ASRS forensics: record what broke + the rollback target (last healthy checkpoint), so the
            # loop can avoid repeating the failure class. Best-effort — never alters the gate's verdict.
            try:
                CP.record_failure(repo, broken_patch_sha=H._sha(patch), failure_reason=why,
                                  affected_modules=IG.changed_files(patch or ""), triggered_by=task[:200])
            except Exception:  # noqa: BLE001
                pass
            print(f"[/seif] NOT VERIFIED ({why}) — rolled back. receipt h={rec.get('h')}")
            return {"accepted": False, "receipt": rec, "patch": patch, "reason": why, "integrity": integrity}
        # success: land on a branch (never main), PR if a remote exists
        branch = f"seif/{_slug(task)}-{time.strftime('%m%d-%H%M%S', time.gmtime())}-{os.urandom(2).hex()}"
        # commit the EXACT integrity-checked index (-m, not -am) so the PR contents == what was graded
        for c in (["git", "-C", wt, "checkout", "-q", "-b", branch],
                  ["git", "-C", wt, "-c", "user.name=Neo The Architect",
                   "-c", "user.email=founder@efficientlabs.ai", "commit", "-q", "-m",
                   f"seif: {task[:72]}\n\nEvidence: tests pass (exit 0). Receipt {rec.get('h')}.\n"
                   f"Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"]):
            subprocess.run(c, check=True, capture_output=True)
        # L4: register this VERIFIED state as a healthy checkpoint (commit + proof + context signature),
        # chained to the prior healthy one — turns the gate's success into a promotable known-good state.
        # Best-effort: checkpoint bookkeeping must never break a verified landing.
        checkpoint = None
        try:
            commit = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"],
                                    capture_output=True, text=True).stdout.strip()
            checkpoint = CP.create(
                repo, task[:80], commit=commit,
                proof={"outcome": "pass", "receipt": rec.get("h"), "test_cmd": test_cmd,
                       "exit_code": (result or {}).get("exit_code")},
                context={"task": task, "files_changed": IG.changed_files(patch or "")},
                parent=(CP.last_healthy(repo) or {}).get("id"))
        except Exception:  # noqa: BLE001
            checkpoint = None
        # honest landing state: 'accepted' = tests passed (true regardless); 'landed' = push+PR actually succeeded
        pr_url, landed = None, False
        if make_pr and _has_remote(repo):
            push = subprocess.run(["git", "-C", wt, "push", "-q", "-u", "origin", branch], capture_output=True, text=True)
            if push.returncode != 0:
                pr_url = f"(push failed rc={push.returncode}: {push.stderr[-160:]})"
            else:
                slug = _repo_slug(repo)
                pr = subprocess.run(["gh", "pr", "create", "-R", slug or repo, "--head", branch, "--fill"],
                                    cwd=wt, capture_output=True, text=True)
                if pr.returncode == 0:
                    pr_url, landed = pr.stdout.strip(), True
                else:
                    pr_url = f"(branch pushed; pr create rc={pr.returncode}: {pr.stderr[-160:]})"
        where = pr_url or ("local branch only (no remote)" if not make_pr or not _has_remote(repo) else None)
        cp_id = (checkpoint or {}).get("id")
        print(f"[/seif] VERIFIED ✓  branch={branch}  landed={landed}  where={where}  "
              f"receipt h={rec.get('h')}  checkpoint={cp_id}")
        # leave the worktree in place so the founder can inspect; caller/founder removes after merge
        return {"accepted": True, "landed": landed, "branch": branch, "pr": pr_url, "worktree": wt,
                "receipt": rec, "patch": patch, "reason": "verified", "integrity": integrity,
                "checkpoint": checkpoint}
    except Exception:
        H.discard(repo, wt)
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--test", required=True, dest="test_cmd")
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--base", default="HEAD",
                    help="clean-room base ref (default HEAD); 'last-healthy' resolves to the last healthy L4 checkpoint")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--no-pr", action="store_true")
    a = ap.parse_args()
    r = seif_run(a.repo, a.task, a.test_cmd, budget=a.budget, base=a.base, timeout=a.timeout, make_pr=not a.no_pr)
    sys.exit(0 if r["accepted"] else 1)


def _selftest():
    """Real git repo + injected editor (no LLM): the integrity gate must REJECT a test-editing 'pass'
    and ACCEPT an honest source fix, leaving main untouched."""
    import tempfile
    import textwrap
    global _claude_edit
    repo = tempfile.mkdtemp(prefix="seif-run-")
    CP.LEDGER = os.path.join(repo, "_checkpoints.jsonl")          # temp registries — don't touch the real ledger
    CP.FAILURES = os.path.join(repo, "_failures.jsonl")
    g = lambda *a: subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                  check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", repo], check=True)
    open(os.path.join(repo, "calc.py"), "w").write("def add(a, b):\n    return a - b\n")   # bug
    open(os.path.join(repo, "test_calc.py"), "w").write(textwrap.dedent("""\
        import unittest
        from calc import add
        class T(unittest.TestCase):
            def test_add(self):
                self.assertEqual(add(2, 3), 5)
        """))
    g("add", "-A"); g("commit", "-qm", "base")
    cmd = f"{sys.executable} -m unittest -q test_calc"
    orig = _claude_edit
    try:
        # case 1: CHEAT by rewriting the test to trivially pass -> integrity gate must reject
        def cheat(wt, *a, **k):
            open(os.path.join(wt, "test_calc.py"), "w").write(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
            return 0
        _claude_edit = cheat
        r1 = seif_run(repo, "make tests pass", cmd, budget=1, base="HEAD", make_pr=False)
        assert not r1["accepted"] and r1["reason"] == "integrity_violation", r1
        assert any(h["file"].endswith("test_calc.py") for h in r1["integrity"]["hard"]), r1["integrity"]
        # rejection recorded ASRS failure forensics (no checkpoint created for an unverified state)
        fails = CP._read(CP.FAILURES)
        assert fails and fails[-1]["failure_reason"] == "integrity_violation", fails
        assert CP.last_healthy(repo) is None, "no checkpoint may exist before any verified run"

        # case 2: HONEST source fix -> accepted, lands on a local branch (no remote)
        def honest(wt, *a, **k):
            open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
            return 0
        _claude_edit = honest
        r2 = seif_run(repo, "fix add", cmd, budget=1, base="HEAD", make_pr=False)
        assert r2["accepted"] and r2["reason"] == "verified", r2
        # L4: the verified run registered a healthy checkpoint (commit + proof + context)
        assert r2["checkpoint"] and r2["checkpoint"]["proof"]["outcome"] == "pass", r2["checkpoint"]
        lh = CP.last_healthy(repo)
        assert lh and lh["id"] == r2["checkpoint"]["id"], "verified run must become the last healthy checkpoint"
        assert "calc.py" in lh["context"]["files_changed"], lh["context"]
        assert CP.verify_chain(CP.LEDGER)[0], "checkpoint chain must verify"
        H.discard(repo, r2["worktree"])
        # main never touched (still the buggy version)
        assert open(os.path.join(repo, "calc.py")).read().strip().endswith("a - b"), "main untouched"
        print("seif_run selftest PASS — integrity gate REJECTS test-editing, ACCEPTS honest fix; "
              "verified run mints a healthy L4 checkpoint; rejection records ASRS forensics; main untouched")
    finally:
        _claude_edit = orig
        import shutil
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
