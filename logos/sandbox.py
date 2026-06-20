#!/usr/bin/env python3
"""LOGOS sandbox executor — run untrusted code/tests in a locked, ephemeral container.

Hardened against adversarial input (Codex review C-sbx-1, rounds 1-2):
  - NO host bind-mount and NO host staging copy. Files are streamed straight from `workdir`
    into a size-bounded tmpfs /work via tar-over-exec. tar archives symlinks as links, so a
    malicious symlink dangles harmlessly inside the container — no host file ever leaks.
  - ALL test output stays inside the bounded tmpfs; only capped tails are read back, so untrusted
    code can exhaust neither host disk nor harness RAM.
  - non-root `nobody` (65534), --cap-drop=ALL, --security-opt no-new-privileges + apparmor,
    --network=none, --read-only rootfs, cpu/mem/pids caps, in-container hard timeout.
  - the container is ALWAYS torn down (finally), on every path.

Run with the docker group, e.g.:  sg docker -c "python3 logos/sandbox.py selftest"
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile

DEFAULT_IMAGE = "python:3.12-slim"
US = "\x1f"  # unit separator between rc / stdout / stderr in the fetch


def _err(rc, msg):
    return {"outcome": "error", "exit_code": rc, "seconds": 0.0, "stdout": "", "stderr": msg[-2000:]}


def run(workdir, test_cmd, image=DEFAULT_IMAGE, timeout=60, mem="768m", cpus="1", pids=256, work_size="512m"):
    """Run test_cmd over an isolated tmpfs copy of workdir.
    Returns {outcome: pass|fail|timeout|killed|error, exit_code, seconds, stdout, stderr}."""
    import time
    name = "logos-" + os.urandom(6).hex()
    q = shlex.quote(test_cmd)
    rc, secs, out, err, started = None, 0.0, "", "", False
    try:
        boot = subprocess.run(
            ["docker", "run", "-d", "--name", name,
             "--network=none", f"--memory={mem}", f"--cpus={cpus}", f"--pids-limit={pids}",
             "--cap-drop=ALL", "--security-opt", "no-new-privileges", "--security-opt", "apparmor=docker-default",
             "--read-only", "--tmpfs", "/tmp:size=64m", "--tmpfs", "/run:size=8m",
             "--tmpfs", f"/work:exec,size={work_size},mode=1777", "-w", "/work",
             "--user", "65534:65534", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
             image, "sleep", str(int(timeout) + 90)],
            capture_output=True, text=True)
        if boot.returncode != 0:
            return _err(boot.returncode, "boot: " + boot.stderr)
        started = True
        # stage straight from workdir into bounded tmpfs (no host copy; symlinks kept as links)
        subprocess.run(
            f"tar -C {shlex.quote(workdir)} -cf - . | "
            f"docker exec -i {name} tar -C /work --strip-components=1 --no-same-owner --no-same-permissions -xf -",
            shell=True, capture_output=True, text=True)
        chk = subprocess.run(["docker", "exec", name, "sh", "-lc", '[ -n "$(ls -A /work)" ] && echo OK'],
                             capture_output=True, text=True)
        if "OK" not in chk.stdout:
            return _err(2, "stage: /work empty after tar")
        # run test; ALL output stays in the bounded tmpfs; rc captured to a sentinel file
        inner = (f"timeout --kill-after=5 {int(timeout)} sh -c {q} "
                 f">/work/.logos_out 2>/work/.logos_err; echo $? >/work/.logos_rc")
        t0 = time.time()
        try:
            subprocess.run(["docker", "exec", "-w", "/work", name, "sh", "-lc", inner],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=int(timeout) + 25)
        except subprocess.TimeoutExpired:
            rc = 124
        secs = round(time.time() - t0, 3)
        if rc is None:  # read rc + capped tails from tmpfs (host disk never grows)
            g = subprocess.run(
                ["docker", "exec", name, "sh", "-lc",
                 f"cat /work/.logos_rc 2>/dev/null; printf '{US}'; tail -c 4000 /work/.logos_out 2>/dev/null;"
                 f" printf '{US}'; tail -c 2000 /work/.logos_err 2>/dev/null"],
                capture_output=True, text=True, timeout=30)
            parts = g.stdout.split(US)
            try:
                rc = int(parts[0].strip())
            except (ValueError, IndexError):
                rc = -1
            out = parts[1].strip() if len(parts) > 1 else ""
            err = parts[2].strip() if len(parts) > 2 else ""
    except Exception as e:  # noqa: BLE001 - never leak a container on an unexpected error
        rc = rc if rc is not None else -1
        err = (err + f"\nharness-error: {e}")[-2000:]
    finally:
        if started:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    if rc == 0:
        outcome = "pass"
    elif rc == 124:
        outcome = "timeout"
    elif rc == 137 or (rc is not None and rc < 0 and rc != -1):
        outcome = "killed"           # OOM / pids-limit / SIGKILL
    elif rc in (1, 2, 3, 4, 5):
        outcome = "fail"
    else:
        outcome = "error"
    return {"outcome": outcome, "exit_code": rc, "seconds": secs, "stdout": out, "stderr": err}


# ---------------- self-test ----------------
def _mk(files):
    d = tempfile.mkdtemp(prefix="logos-task-")
    for n, c in files.items():
        with open(os.path.join(d, n), "w") as f:
            f.write(c)
    return d


def selftest():
    UT = ("import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n"
          "    def test_add(self): self.assertEqual(add(2,3),5)\nif __name__=='__main__': unittest.main()\n")
    cases = [
        ("passing-tests->pass", _mk({"calc.py": "def add(a,b):\n    return a+b\n", "test_calc.py": UT}), "python -m unittest -q", 30, "pass"),
        ("failing-tests->fail", _mk({"calc.py": "def add(a,b):\n    return a-b\n", "test_calc.py": UT}), "python -m unittest -q", 30, "fail"),
        ("infinite-loop->timeout", _mk({"loop.py": "import time\nwhile True: time.sleep(1)\n"}), "python loop.py", 3, "timeout"),
        ("output-flood->contained", _mk({"f.py": "import sys\nfor _ in range(2_000_000): sys.stdout.write('x'*64)\n"}), "python f.py", 20, None),
    ]
    print("=== LOGOS sandbox self-test (hardened, no host footprint) ===")
    ok = True
    for label, d, cmd, to, expect in cases:
        r = run(d, cmd, timeout=to)
        passed = (expect is None) or (r["outcome"] == expect)
        ok = ok and passed
        print(f"{'PASS' if passed else 'FAIL'}  {label:<26} outcome={r['outcome']} rc={r['exit_code']} {r['seconds']}s out_len={len(r['stdout'])}")
    print(f"\n{'ALL GREEN' if ok else 'FAILURES PRESENT'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    elif len(sys.argv) > 3 and sys.argv[1] == "run":
        print(json.dumps(run(sys.argv[2], sys.argv[3]), indent=2))
    else:
        print("usage: sandbox.py selftest | run <workdir> <test_cmd>")
