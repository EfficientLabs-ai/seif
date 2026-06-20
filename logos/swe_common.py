#!/usr/bin/env python3
"""Shared helpers for both arms — so Arm A (blind) and Arm B (LOGOS) operate on PROVABLY
identical inputs. The only intended difference between the arms is the execution-feedback loop;
the clone, the test-edit guard, and the predictions format are byte-for-byte the same here.

The clone sequence is identical to swe_arm_a.run_arm_a: clone repo@base_commit -> STRIP .git
history (no upstream-fix leak) -> re-init a clean base commit so `git diff` still works.
"""
import json
import os
import re
import subprocess

TEST_RE = re.compile(r"(^|/)tests?/|(^|/)conftest\.py$|(^|/)test_[^/]*\.py$|_test\.py$")


def prepare_clone(inst, repo_dir):
    """Clone inst@base_commit into repo_dir and strip history. Identical for both arms."""
    subprocess.run(["git", "clone", "--quiet", f"https://github.com/{inst['repo']}.git", repo_dir], check=True)
    subprocess.run(["git", "-C", repo_dir, "checkout", "--quiet", inst["base_commit"]], check=True)
    subprocess.run(["rm", "-rf", os.path.join(repo_dir, ".git")], check=True)
    for c in (["git", "-C", repo_dir, "init", "-q"],
              ["git", "-C", repo_dir, "add", "-A"],
              ["git", "-C", repo_dir, "-c", "user.name=base", "-c", "user.email=b@b", "commit", "-q", "-m", "base"]):
        subprocess.run(c, check=True, capture_output=True)


def staged_diff(repo_dir, exclude=()):
    """Stage ALL changes incl. new files, then return the cached diff (the candidate patch).
    `exclude` is a list of repo-relative paths to drop via pathspec (e.g. the Arm-B repro scaffold),
    so they can never enter the prediction patch regardless of staging order."""
    subprocess.run(["git", "-C", repo_dir, "add", "-A"], capture_output=True)
    cmd = ["git", "-C", repo_dir, "diff", "--cached"]
    if exclude:
        cmd += ["--", "."] + [f":(exclude){p}" for p in exclude]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def filter_tests(diff):
    """Drop per-file diff sections touching test paths — neither arm may edit graded tests."""
    out, keep = [], True
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            keep = not (m and TEST_RE.search(m.group(2)))
        if keep:
            out.append(line)
    return "".join(out)


def write_prediction(preds_dir, iid, model_name, diff, raw, meta_extra):
    os.makedirs(preds_dir, exist_ok=True)
    base = os.path.join(preds_dir, f"{model_name}_{iid}")
    with open(base + ".jsonl", "w") as f:
        f.write(json.dumps({"instance_id": iid, "model_name_or_path": model_name, "model_patch": diff}) + "\n")
    meta = {"instance_id": iid, "patch_bytes": len(diff), "raw_bytes": len(raw), "empty": not diff.strip()}
    meta.update(meta_extra)
    json.dump(meta, open(base + ".meta.json", "w"), indent=2)
    return base
