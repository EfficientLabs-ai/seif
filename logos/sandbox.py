#!/usr/bin/env python3
"""LOGOS sandbox executor — run untrusted code/tests in a locked, ephemeral Docker container.

Deterministic, isolated, disposable. The reward function of the whole system rides on this:
inject a working copy -> run a test command -> capture exit/stdout/stderr -> demux -> destroy.

Isolation (research-locked): --network=none --memory --cpus --pids-limit --cap-drop=ALL
--read-only rootfs (+ tmpfs /tmp,/run), writable /work mount, non-root --user, external hard timeout.
Run the harness with the docker group, e.g.:  sg docker -c "python3 logos/sandbox.py selftest"
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


def run(workdir, test_cmd, image=DEFAULT_IMAGE, timeout=60, mem="256m", cpus="1", pids=256):
    """Run test_cmd inside an isolated container over a fresh copy of workdir.
    Returns a dict: outcome(pass|fail|timeout|killed|error), exit_code, stdout, stderr, seconds."""
    tmp = tempfile.mkdtemp(prefix="logos-sbx-")
    work = os.path.join(tmp, "work")
    shutil.copytree(workdir, work)
    name = "logos-" + uuid.uuid4().hex[:12]
    inner = f"timeout --kill-after=5 {int(timeout)} sh -c {shlex.quote(test_cmd)}"
    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network=none", f"--memory={mem}", f"--cpus={cpus}", f"--pids-limit={pids}",
        "--cap-drop=ALL", "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/run",
        "-v", f"{work}:/work", "-w", "/work",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
        image, "sh", "-lc", inner,
    ]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=int(timeout) + 25)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        rc, out, err = 124, "", "harness-timeout(docker-hang)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    secs = round(time.time() - t0, 3)

    if rc == 0:
        outcome = "pass"
    elif rc == 124:
        outcome = "timeout"          # external `timeout` hard limit reached
    elif rc == 137 or rc < 0:
        outcome = "killed"           # OOM / pids-limit / SIGKILL
    elif rc in (1, 2, 3, 4, 5):
        outcome = "fail"             # test failures / collection errors
    else:
        outcome = "error"
    return {"outcome": outcome, "exit_code": rc, "seconds": secs,
            "stdout": out[-4000:], "stderr": err[-2000:]}


# ---------------- self-test ----------------
def _mk(files):
    d = tempfile.mkdtemp(prefix="logos-task-")
    for name, content in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(content)
    return d


def selftest():
    results = []

    passing = _mk({
        "calc.py": "def add(a,b):\n    return a+b\n",
        "test_calc.py": "import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2,3),5)\nif __name__=='__main__': unittest.main()\n",
    })
    r = run(passing, "python -m unittest -q", timeout=30)
    results.append(("passing-tests->pass", r["outcome"] == "pass", r))

    failing = _mk({
        "calc.py": "def add(a,b):\n    return a-b\n",  # bug
        "test_calc.py": "import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2,3),5)\nif __name__=='__main__': unittest.main()\n",
    })
    r = run(failing, "python -m unittest -q", timeout=30)
    results.append(("failing-tests->fail", r["outcome"] == "fail", r))

    looping = _mk({"loop.py": "import time\nwhile True: time.sleep(1)\n"})
    r = run(looping, "python loop.py", timeout=3)
    results.append(("infinite-loop->timeout", r["outcome"] == "timeout", r))

    print("=== LOGOS sandbox self-test ===")
    ok = True
    for name, passed, r in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name:<26} outcome={r['outcome']} rc={r['exit_code']} {r['seconds']}s")
        ok = ok and passed
    print(f"\n{'ALL GREEN' if ok else 'FAILURES PRESENT'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    elif len(sys.argv) > 3 and sys.argv[1] == "run":
        print(json.dumps(run(sys.argv[2], sys.argv[3]), indent=2))
    else:
        print("usage: sandbox.py selftest | run <workdir> <test_cmd>")
