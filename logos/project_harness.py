#!/usr/bin/env python3
"""SEIF Agent Harness — PROJECT MODE (your repos, your tests). The execution oracle for real work.

This is the P1 foundation of `/seif`: an ATMS clean-room (git worktree) + evidence adjudication (your
project's own test command's OS exit code) + a signed receipt + automatic rollback on failure. For your
OWN repos there is no graded-test oracle to protect — your full suite IS the ground truth — so this is
simpler than the eval harness: run everything, exit 0 = verified, exit >0 = rejected + rolled back.

Safety: all work happens in an EPHEMERAL git worktree; main is never touched. A failed change is
discarded (ATMS rollback). A passed change is left in the worktree for the caller to turn into a
branch/PR — never an auto-merge. Every attempt (pass or fail) mints a receipt.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kernel"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import seif_kernel as K     # noqa: E402
except Exception:               # noqa: BLE001
    K = None
import integrity_guard as IG    # noqa: E402  (universal gate-bypass-sentinel check on every accepted patch)

RECEIPTS = os.path.expanduser("~/seif/kernel/ledger/project_receipts.jsonl")


def _sha(s):
    return hashlib.sha256((s or "").encode()).hexdigest()[:16]


DEP_DIRS = ("node_modules", ".venv", "venv", "vendor", ".yarn", ".tox")


def checkpoint(repo, base="HEAD", link_deps=True):
    """Ephemeral, detached git worktree from `base` — the clean room. Returns its path.

    git worktree only checks out TRACKED files, so gitignored installed-dependency dirs (node_modules,
    .venv, …) are absent — which makes any real repo's tests fail with import errors that LOOK like code
    bugs but aren't. We symlink those dep dirs from the source repo (read-only during tests) so the
    clean room reflects the repo's actual runnable state. (Discovered dogfooding StratosAgent: its
    14/14 suites "failed" in a bare worktree purely because node_modules was missing.)"""
    wt = tempfile.mkdtemp(prefix="seif-wt-")
    subprocess.run(["git", "-C", repo, "worktree", "add", "--quiet", "--detach", wt, base], check=True)
    # The clean room is a CONTROLLED, separately-gated environment (its verdict is the project's test suite,
    # not the interactive Stop hook). Pre-place the Stop-hook bypass so the nested editor sub-agent isn't
    # blocked here — AND git-exclude it so it can NEVER stage into the candidate patch. (Dogfood: without
    # this, the sub-agent created .seif-gate-off itself to finish and it leaked into a StratosAgent #1 patch.)
    try:
        open(os.path.join(wt, ".seif-gate-off"), "w").write(
            "seif clean-room: interactive Stop hook bypassed here; the harness test suite is the gate.\n")
    except OSError:
        pass
    if link_deps:
        for d in DEP_DIRS:
            src = os.path.join(repo, d)
            dst = os.path.join(wt, d)
            if os.path.isdir(src) and not os.path.exists(dst):
                try:
                    os.symlink(src, dst)
                except OSError:
                    continue
        # git-ignore the symlinked dep dirs in THIS worktree so `git add -A` never stages them
        # (a bare symlink named 'node_modules' isn't matched by a 'node_modules/' .gitignore rule).
        try:
            excl = subprocess.run(["git", "-C", wt, "rev-parse", "--git-path", "info/exclude"],
                                  capture_output=True, text=True).stdout.strip()
            if excl:
                with open(os.path.join(wt, excl) if not os.path.isabs(excl) else excl, "a") as f:
                    f.write("\n# seif: ignore symlinked dependency dirs\n" + "\n".join("/" + d for d in DEP_DIRS) + "\n")
        except Exception:  # noqa: BLE001
            pass
    # always exclude the gate-bypass sentinel from staging (independent of link_deps)
    try:
        excl = subprocess.run(["git", "-C", wt, "rev-parse", "--git-path", "info/exclude"],
                              capture_output=True, text=True).stdout.strip()
        if excl:
            with open(os.path.join(wt, excl) if not os.path.isabs(excl) else excl, "a") as f:
                f.write("\n# seif: never stage the Stop-hook bypass sentinel (any dir)\n.seif-gate-off\n")
    # NOTE (scope): this exclude is a soft convenience; the HARD guarantee is integrity_guard's
    # gate_bypass_sentinel check, run in BOTH seif_run and verify_change, which rejects the file even if it
    # is force-added. KNOWN GAP (queued): a *global* ~/.claude/.seif-gate-off created as a side-effect tool
    # action is outside any patch, so the patch-scoped guard can't see it — that needs ledger-level
    # monitoring (the PostToolUse action ledger), tracked separately.
    except Exception:  # noqa: BLE001
        pass
    return wt


def discard(repo, wt):
    """ATMS rollback — remove the worktree and its changes; main is untouched."""
    subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt], capture_output=True)
    shutil.rmtree(wt, ignore_errors=True)


def run_tests(wt, test_cmd, timeout=600):
    """Run the project's own test command in the worktree. GROUND TRUTH = exit code."""
    t0 = time.time()
    try:
        p = subprocess.run(test_cmd, cwd=wt, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"exit_code": p.returncode, "outcome": "pass" if p.returncode == 0 else "fail",
                "seconds": round(time.time() - t0, 1), "stdout": p.stdout[-3000:], "stderr": p.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "outcome": "timeout", "seconds": timeout, "stdout": "", "stderr": "timeout"}


def _receipt(repo, task, test_cmd, result, patch, usage=None, metering=None):
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "actor": "seif-harness", "repo": os.path.basename(repo.rstrip("/")), "task": str(task)[:200],
        "test_cmd": test_cmd, "patch_sha": _sha(patch), "patch_bytes": len(patch or ""),
        "exit_code": result.get("exit_code"), "outcome": result.get("outcome"),
        "seconds": result.get("seconds"), "evidence": "os-exit-code; project test suite; no LLM interpretation",
    }
    # token + cost accounting (optional): makes a receipt cost-attributable so a spend claim is MEASURED.
    # Added before the hash so usage is covered by the receipt's integrity chain.
    if usage is not None:
        rec["usage"] = usage
    # production metering (optional): the A-loop's per-task record fields — attempt_number,
    # empty_response_retries, checkpoint_id, evidence_result, final_outcome. Merged in BEFORE the hash so
    # every field is covered by the receipt's integrity chain (a receipt's claim about which attempt/budget
    # step produced the patch, how many empty-response retries were absorbed, which healthy checkpoint was
    # minted, and the final disposition is tamper-evident, not after-the-fact narrative). Optional → old
    # receipts (and callers that pass no metering) keep their exact shape + chain.
    if metering is not None:
        for k, v in metering.items():
            rec[k] = v
    try:
        os.makedirs(os.path.dirname(RECEIPTS), exist_ok=True)
        prev = "0" * 16
        if os.path.exists(RECEIPTS):
            last = ""
            for line in open(RECEIPTS):
                if line.strip():
                    last = line.strip()
            if last:
                prev = json.loads(last).get("h", prev)
        rec["prev"] = prev
        rec["h"] = hashlib.sha256((prev + json.dumps(rec, sort_keys=True)).encode()).hexdigest()[:16]
        with open(RECEIPTS, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[harness] receipt: {e!r}\n")
    return rec


def verify_change(repo, test_cmd, make_change, task="change", base="HEAD", timeout=600):
    """Clean-room a worktree, let `make_change(worktree_path)` edit it, run the project's tests, decide by
    exit code, mint a receipt, and roll back on failure. Returns dict with accepted/worktree/patch/result/receipt.
    On accept, the worktree is LEFT for the caller to branch/PR (never auto-merged)."""
    wt = checkpoint(repo, base)
    try:
        make_change(wt)
        subprocess.run(["git", "-C", wt, "add", "-A"], capture_output=True)
        patch = subprocess.run(["git", "-C", wt, "diff", "--cached"], capture_output=True, text=True).stdout
        # Universal gate-integrity check (independent of any task protected set): a patch that adds a
        # gate-bypass sentinel (e.g. .seif-gate-off, even force-added) is REJECTED here too — verify_change
        # is a second accept path and must not be a hole around seif_run's integrity gate.
        clean, igrep = IG.is_clean(patch, [])
        if not clean:
            discard(repo, wt)
            return {"accepted": False, "worktree": None, "patch": patch,
                    "result": {"outcome": "integrity_violation", "exit_code": None}, "integrity": igrep,
                    "receipt": _receipt(repo, task, test_cmd, {"outcome": "integrity_violation", "exit_code": None}, patch)}
        result = run_tests(wt, test_cmd, timeout=timeout)
        rec = _receipt(repo, task, test_cmd, result, patch)
        if result["outcome"] == "pass":
            return {"accepted": True, "worktree": wt, "patch": patch, "result": result, "receipt": rec}
        discard(repo, wt)                                  # ATMS rollback
        return {"accepted": False, "worktree": None, "patch": patch, "result": result, "receipt": rec}
    except Exception:
        discard(repo, wt)
        raise


# ---------------- self-test (real git, real pytest, no docker) ----------------
def _selftest():
    import textwrap
    repo = tempfile.mkdtemp(prefix="seif-proj-")
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", repo], check=True)
    open(os.path.join(repo, "calc.py"), "w").write("def add(a, b):\n    return a - b\n")   # bug
    open(os.path.join(repo, "test_calc.py"), "w").write(textwrap.dedent("""\
        import unittest
        from calc import add
        class T(unittest.TestCase):
            def test_add(self):
                self.assertEqual(add(2, 3), 5)
        """))
    run("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    cmd = f"{sys.executable} -m unittest -q test_calc"   # stdlib, dependency-free (real test_cmd is founder-configured)

    def good(wt):
        open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")

    def bad(wt):
        open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a * b\n")

    r_bad = verify_change(repo, cmd, bad, task="wrong fix")
    assert not r_bad["accepted"] and r_bad["worktree"] is None, r_bad
    r_good = verify_change(repo, cmd, good, task="correct fix")
    assert r_good["accepted"] and r_good["result"]["outcome"] == "pass", r_good
    assert "calc.py" in r_good["patch"], "patch captured"
    # main repo untouched (still the buggy version) + worktrees cleaned (only the accepted one remains)
    assert open(os.path.join(repo, "calc.py")).read().strip().endswith("a - b"), "main untouched"
    discard(repo, r_good["worktree"])
    print(f"project_harness selftest PASS — bad fix rolled back, good fix accepted+receipted, main untouched")
    print(f"  receipt outcome(good)={r_good['receipt']['outcome']} exit={r_good['receipt']['exit_code']} "
          f"chain_h={r_good['receipt'].get('h')}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: project_harness.py --selftest  (verify_change is the API the /seif driver calls)")
