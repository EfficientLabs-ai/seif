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

CLAUDE = "/home/neo/.local/bin/claude"


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


def seif_run(repo, task, test_cmd, budget=3, base="HEAD", timeout=600, make_pr=True):
    repo = os.path.abspath(repo)
    wt = H.checkpoint(repo, base)
    feedback, passed, result, patch = "", False, None, ""
    print(f"[/seif] repo={os.path.basename(repo)} test='{test_cmd}' budget={budget}\n[/seif] clean room: {wt}")
    try:
        for step in range(1, budget + 1):
            rc = _claude_edit(wt, task, feedback, step == 1, timeout)
            subprocess.run(["git", "-C", wt, "add", "-A"], capture_output=True)
            patch = subprocess.run(["git", "-C", wt, "diff", "--cached"], capture_output=True, text=True).stdout
            if not patch.strip():
                print(f"[/seif] step {step}: agent made no change (rc={rc}) — stop")
                break
            result = H.run_tests(wt, test_cmd, timeout=timeout)
            print(f"[/seif] step {step}: tests -> {result['outcome']} (exit {result['exit_code']}, {result['seconds']}s)")
            if result["outcome"] == "pass":
                passed = True
                break
            feedback = (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-4500:]
        rec = H._receipt(repo, task, test_cmd, result or {"outcome": "no_change", "exit_code": None}, patch)
        if not passed:
            H.discard(repo, wt)                                   # ATMS rollback — main untouched
            print(f"[/seif] NOT VERIFIED — rolled back. receipt h={rec.get('h')}")
            return {"accepted": False, "receipt": rec, "patch": patch}
        # success: land on a branch (never main), PR if a remote exists
        branch = f"seif/{_slug(task)}-{time.strftime('%m%d-%H%M%S', time.gmtime())}-{os.urandom(2).hex()}"
        for c in (["git", "-C", wt, "checkout", "-q", "-b", branch],
                  ["git", "-C", wt, "-c", "user.name=Neo The Architect",
                   "-c", "user.email=founder@efficientlabs.ai", "commit", "-q", "-am",
                   f"seif: {task[:72]}\n\nEvidence: tests pass (exit 0). Receipt {rec.get('h')}.\n"
                   f"Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"]):
            subprocess.run(c, check=True, capture_output=True)
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
        print(f"[/seif] VERIFIED ✓  branch={branch}  landed={landed}  where={where}  receipt h={rec.get('h')}")
        # leave the worktree in place so the founder can inspect; caller/founder removes after merge
        return {"accepted": True, "landed": landed, "branch": branch, "pr": pr_url,
                "worktree": wt, "receipt": rec, "patch": patch}
    except Exception:
        H.discard(repo, wt)
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--test", required=True, dest="test_cmd")
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--no-pr", action="store_true")
    a = ap.parse_args()
    r = seif_run(a.repo, a.task, a.test_cmd, budget=a.budget, base=a.base, timeout=a.timeout, make_pr=not a.no_pr)
    sys.exit(0 if r["accepted"] else 1)


if __name__ == "__main__":
    main()
