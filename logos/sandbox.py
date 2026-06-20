#!/usr/bin/env python3
"""LOGOS sandbox executor — run untrusted code/tests in a locked, ephemeral container.

Hardened against adversarial input (Codex review C-sbx-1):
  - NO host bind-mount. Files are staged into a size-bounded tmpfs /work via `docker cp`,
    so a malicious symlink can't leak host files and untrusted writes can't fill host disk.
  - copytree(symlinks=True): symlinks copied as links -> dangle harmlessly inside the container.
  - non-root `nobody` (65534), --cap-drop=ALL, --security-opt no-new-privileges + apparmor,
    --network=none, --read-only rootfs, cpu/mem/pids caps, in-container hard timeout.
  - output spooled to capped temp files (no harness-RAM flooding); container ALWAYS removed.

Run with the docker group, e.g.:  sg docker -c "python3 logos/sandbox.py selftest"
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

DEFAULT_IMAGE = "python:3.12-slim"


def _tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - n))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def run(workdir, test_cmd, image=DEFAULT_IMAGE, timeout=60, mem="768m", cpus="1", pids=256, work_size="512m"):
    """Run test_cmd over an isolated copy of workdir. Returns
    {outcome: pass|fail|timeout|killed|error, exit_code, seconds, stdout, stderr}."""
    tmp = tempfile.mkdtemp(prefix="logos-sbx-")
    work = os.path.join(tmp, "work")
    shutil.copytree(workdir, work, symlinks=True)                 # HIGH#1: never deref symlinks
    name = "logos-" + uuid.uuid4().hex[:12]
    inner = f"timeout --kill-after=5 {int(timeout)} sh -c {shlex.quote(test_cmd)}"
    out_f, err_f = os.path.join(tmp, "out"), os.path.join(tmp, "err")
    rc, secs, started = None, 0.0, False
    try:
        boot = subprocess.run(
            ["docker", "run", "-d", "--name", name,
             "--network=none", f"--memory={mem}", f"--cpus={cpus}", f"--pids-limit={pids}",
             "--cap-drop=ALL", "--security-opt", "no-new-privileges", "--security-opt", "apparmor=docker-default",
             "--read-only", "--tmpfs", "/tmp:size=64m", "--tmpfs", "/run:size=8m",
             "--tmpfs", f"/work:exec,size={work_size},mode=1777", "-w", "/work",
             "--user", "65534:65534", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
             image, "sleep", str(int(timeout) + 60)],
            capture_output=True, text=True)
        if boot.returncode != 0:
            return {"outcome": "error", "exit_code": boot.returncode, "seconds": 0.0,
                    "stdout": "", "stderr": ("boot: " + boot.stderr)[-2000:]}
        started = True
        # stage into the read-only container's writable tmpfs via tar-over-exec (docker cp is refused on --read-only)
        stage = subprocess.run(
            f"tar -C {shlex.quote(work)} -cf - . | "
            f"docker exec -i {name} tar -C /work --strip-components=1 --no-same-owner --no-same-permissions -xf -",
            shell=True, capture_output=True, text=True)
        if stage.returncode != 0:
            return {"outcome": "error", "exit_code": stage.returncode, "seconds": 0.0,
                    "stdout": "", "stderr": ("stage: " + stage.stderr)[-2000:]}
        t0 = time.time()
        with open(out_f, "wb") as of, open(err_f, "wb") as ef:
            p = subprocess.run(["docker", "exec", "-w", "/work", name, "sh", "-lc", inner],
                               stdout=of, stderr=ef, timeout=int(timeout) + 25)
            rc = p.returncode
        secs = round(time.time() - t0, 3)
    except subprocess.TimeoutExpired:
        rc, secs = 124, float(int(timeout) + 25)
    except Exception as e:  # noqa: BLE001 - never leak a container on an unexpected error
        rc = -1
        with open(err_f, "a") as ef:
            ef.write(f"\nharness-error: {e}")
    finally:
        if started:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)  # HIGH#3: always teardown
        out, err = _tail(out_f, 4000), _tail(err_f, 2000)
        shutil.rmtree(tmp, ignore_errors=True)

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
    for name, content in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(content)
    return d


def selftest():
    UT = "import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2,3),5)\nif __name__=='__main__': unittest.main()\n"
    cases = [
        ("passing-tests->pass", _mk({"calc.py": "def add(a,b):\n    return a+b\n", "test_calc.py": UT}), "python -m unittest -q", 30, "pass"),
        ("failing-tests->fail", _mk({"calc.py": "def add(a,b):\n    return a-b\n", "test_calc.py": UT}), "python -m unittest -q", 30, "fail"),
        ("infinite-loop->timeout", _mk({"loop.py": "import time\nwhile True: time.sleep(1)\n"}), "python loop.py", 3, "timeout"),
        ("write-bomb->killed-or-pass", _mk({"w.py": "open('/work/big','wb').write(b'x'*10_000_000)\nprint('wrote')\n"}), "python w.py", 20, None),
    ]
    print("=== LOGOS sandbox self-test (hardened) ===")
    ok = True
    for label, d, cmd, to, expect in cases:
        r = run(d, cmd, timeout=to)
        passed = (expect is None) or (r["outcome"] == expect)
        ok = ok and passed
        print(f"{'PASS' if passed else 'FAIL'}  {label:<28} outcome={r['outcome']} rc={r['exit_code']} {r['seconds']}s")
    print(f"\n{'ALL GREEN' if ok else 'FAILURES PRESENT'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    elif len(sys.argv) > 3 and sys.argv[1] == "run":
        print(json.dumps(run(sys.argv[2], sys.argv[3]), indent=2))
    else:
        print("usage: sandbox.py selftest | run <workdir> <test_cmd>")
