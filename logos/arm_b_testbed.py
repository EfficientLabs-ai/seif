#!/usr/bin/env python3
"""Arm-B execution-feedback sandbox — run the agent's CURRENT edits against runnable code inside
the per-instance SWE-bench testbed (where the repo's deps are actually installed), so the LOGOS
loop gets real execution signal. The held-out grading tests (test_patch) are NEVER present here —
they are applied only by the official scorer at grading time — so this leaks no oracle.

Image: the prebuilt `swebench/sweb.eval.x86_64.<iid>` (Docker Hub normalizes `__` -> `_1776_`).
/testbed holds repo@base_commit + the conda env `testbed`. We overlay the agent's edited files onto
/testbed and import them via PYTHONPATH=/testbed (cwd/site shadowing) — directionally correct
feedback without a per-step reinstall. Grading parity is unaffected: the official harness does its
own clean `pip install .` on the final patch.

Isolation: --network=none (deps already baked in), --cap-drop=ALL, no-new-privileges, mem/cpu/pids
caps, container always torn down. Not --read-only (we must overlay /testbed); the container is
ephemeral so its writable layer is discarded on teardown.
"""
import os
import shlex
import subprocess

NS = "swebench"
US = "\x1f"


def image_for(iid):
    return f"{NS}/sweb.eval.x86_64.{iid.replace('__', '_1776_')}:latest"


def ensure_image(iid, timeout=1800):
    """Pull the prebuilt instance image if absent. Returns the local image ref or raises."""
    img = image_for(iid)
    have = subprocess.run(["docker", "image", "inspect", img], capture_output=True)
    if have.returncode == 0:
        return img
    p = subprocess.run(["docker", "pull", img], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"pull failed for {img}: {p.stderr[-400:]}")
    return img


def run_in_testbed(img, host_repo, test_cmd, timeout=120, mem="2g", cpus="2", pids=512):
    """Overlay host_repo onto /testbed in a container from `img`, run test_cmd in conda env testbed.
    Returns {outcome: pass|fail|timeout|error, exit_code, stdout, stderr}."""
    import time
    name = "armb-" + os.urandom(6).hex()
    started, rc, out, err = False, None, "", ""
    try:
        boot = subprocess.run(
            ["docker", "run", "-d", "--name", name,
             "--network=none", f"--memory={mem}", f"--cpus={cpus}", f"--pids-limit={pids}",
             "--cap-drop=ALL", "--security-opt", "no-new-privileges",
             "-w", "/testbed", "-e", "PYTHONDONTWRITEBYTECODE=1",
             img, "sleep", str(int(timeout) + 120)],
            capture_output=True, text=True)
        if boot.returncode != 0:
            return {"outcome": "error", "exit_code": boot.returncode, "stdout": "", "stderr": "boot: " + boot.stderr[-800:]}
        started = True
        # overlay agent edits onto /testbed (exclude VCS; keep /testbed's own .git intact)
        sync = subprocess.run(
            f"tar -C {shlex.quote(host_repo)} --exclude=./.git --exclude=.git --exclude='*/.git' -cf - . | "
            f"docker exec -i {name} tar -C /testbed --no-same-owner --no-same-permissions -xf -",
            shell=True, capture_output=True, text=True)
        if sync.returncode != 0:
            return {"outcome": "error", "exit_code": 2, "stdout": "", "stderr": "sync: " + sync.stderr[-800:]}
        inner = ("source /opt/miniconda3/bin/activate >/dev/null 2>&1; conda activate testbed >/dev/null 2>&1; "
                 "cd /testbed; export PYTHONPATH=/testbed; "
                 f"timeout --kill-after=5 {int(timeout)} sh -c {shlex.quote(test_cmd)} "
                 ">/testbed/.armb_out 2>/testbed/.armb_err; echo $? >/testbed/.armb_rc")
        try:
            subprocess.run(["docker", "exec", name, "bash", "-lc", inner],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=int(timeout) + 40)
        except subprocess.TimeoutExpired:
            rc = 124
        if rc is None:
            g = subprocess.run(
                ["docker", "exec", name, "sh", "-lc",
                 f"cat /testbed/.armb_rc 2>/dev/null; printf '{US}'; tail -c 6000 /testbed/.armb_out 2>/dev/null;"
                 f" printf '{US}'; tail -c 3000 /testbed/.armb_err 2>/dev/null"],
                capture_output=True, text=True, timeout=40)
            parts = g.stdout.split(US)
            try:
                rc = int(parts[0].strip())
            except (ValueError, IndexError):
                rc = -1
            out = parts[1].strip() if len(parts) > 1 else ""
            err = parts[2].strip() if len(parts) > 2 else ""
    except Exception as e:  # noqa: BLE001
        rc = rc if rc is not None else -1
        err = (err + f"\nharness-error: {e}")[-2000:]
    finally:
        if started:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    outcome = "pass" if rc == 0 else ("timeout" if rc == 124 else ("fail" if rc in (1, 2, 3, 4, 5) else "error"))
    return {"outcome": outcome, "exit_code": rc, "stdout": out, "stderr": err}


if __name__ == "__main__":
    import sys
    print(ensure_image(sys.argv[1] if len(sys.argv) > 1 else "psf__requests-2931"))
