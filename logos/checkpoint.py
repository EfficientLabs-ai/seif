#!/usr/bin/env python3
"""SEIF L4 Checkpoint Engine — verified, promotable, replayable system states ("Versioned Intelligence").

A checkpoint is NOT a copy of files, and NOT "the latest attempt". It is a VERIFIED state: a git commit
that passed the gate, plus its PROOF (test outcome + receipt hash) and a CONTEXT SIGNATURE (task, files
changed, assumptions). Creation is PROOF-GATED — you cannot register a checkpoint without evidence it
verified, so "checkpoint" == "known-good" structurally, not by assertion. Records are hash-chained
(tamper-evident lineage), like receipts.

This is the L4 layer above Tripartite Memory (L1 working / L2 episodic / L3 graph): L4 = "thinking STATE".
It turns the gate's per-attempt rollback (discard worktree → base) into a real "roll back to the last
HEALTHY checkpoint" + an evolution lineage (checkpoint_N → delta → checkpoint_N+1), and records ASRS
failure forensics so the loop can avoid repeating a failure class (fed forward via L2 memory).

Scope (v1, deliberately minimal — SEIF microkernel doctrine): create (proof-gated) · last_healthy · get ·
lineage · restore (materialize a checkpoint's commit into a worktree) · record_failure (ASRS forensics) ·
verify_chain. NOT in v1: checkpoint compression, cross-mesh sync, auto-promotion (founder-gated), UI.
Dependency-free (stdlib + git).
"""
import hashlib
import json
import os
import re
import subprocess
import time

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")   # a checkpoint commit must be a git sha (no option-injection)

LEDGER = os.environ.get("SEIF_CHECKPOINTS", os.path.expanduser("~/seif/kernel/ledger/checkpoints.jsonl"))
FAILURES = os.environ.get("SEIF_CHECKPOINT_FAILURES",
                          os.path.expanduser("~/seif/kernel/ledger/checkpoint_failures.jsonl"))


class CheckpointError(Exception):
    pass


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _repo_key(repo):
    return os.path.basename(os.path.abspath(repo).rstrip("/"))


def _read(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue            # tolerate a torn final line
        if isinstance(obj, dict):
            out.append(obj)     # ignore non-object lines (null/list/scalar) — callers assume dicts
    return out


def _append_chained(path, rec):
    """Append a hash-chained record (h = sha256(prev + canonical(body)); body excludes prev/h)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prev = "0" * 16
    for r in _read(path):
        if r.get("h"):
            prev = r["h"]
    rec["prev"] = prev
    rec["h"] = _sha(prev + _canonical({k: rec[k] for k in rec if k not in ("prev", "h")}))
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def create(repo, label, *, commit, proof, context=None, parent=None, healthy=True):
    """Register a VERIFIED state as a checkpoint. PROOF-GATED: proof must be {outcome:'pass', receipt:<h>}
    — refuses to checkpoint an unverified state (the core invariant: a checkpoint is known-good)."""
    if (not isinstance(proof, dict) or proof.get("outcome") != "pass"
            or not isinstance(proof.get("receipt"), str) or not proof["receipt"].strip()):
        raise CheckpointError("checkpoint requires proof={outcome:'pass', receipt:'<hash str>', ...} — "
                              "cannot checkpoint an unverified state")
    if not _SHA_RE.match(str(commit or "")):
        raise CheckpointError("checkpoint requires a git-sha commit ref (the verified state)")
    ctx = context if isinstance(context, dict) else {}
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": _repo_key(repo), "repo_path": os.path.abspath(repo), "label": str(label)[:120],
        "commit": str(commit),
        "proof": {"outcome": proof["outcome"], "receipt": str(proof["receipt"]),
                  "test_cmd": proof.get("test_cmd"), "exit_code": proof.get("exit_code")},
        "context": {"task": str(ctx.get("task", ""))[:300],
                    "files_changed": list(ctx.get("files_changed") or [])[:50],
                    "assumptions": list(ctx.get("assumptions") or [])[:20]},
        "parent": parent, "healthy": bool(healthy), "actor": "checkpoint-engine",
    }
    # nonce → collision-resistant id even for same repo/commit/label within the same second
    rec["id"] = _sha(rec["repo_path"] + rec["commit"] + rec["ts"] + rec["label"] + os.urandom(8).hex())
    return _append_chained(LEDGER, rec)


def lineage(repo):
    """All checkpoints for a repo, oldest→newest. Filter by ABSOLUTE path (two different repos that share
    a folder name must not share lineage); fall back to basename for legacy records without repo_path."""
    ap, k = os.path.abspath(repo), _repo_key(repo)
    return [c for c in _read(LEDGER)
            if c.get("repo_path") == ap or (c.get("repo_path") is None and c.get("repo") == k)]


def get(repo, checkpoint_id):
    return next((c for c in lineage(repo) if c.get("id") == checkpoint_id), None)


def last_healthy(repo):
    """The most recent HEALTHY checkpoint for a repo = the rollback target. None if none yet."""
    h = [c for c in lineage(repo) if c.get("healthy")]
    return h[-1] if h else None


def restore(repo, checkpoint_id, dest):
    """Materialize a checkpoint's verified commit into a fresh DETACHED worktree at `dest` — the 'restore
    checkpoint' op: gives you the known-good state to apply a delta against (never touches main)."""
    cp = get(repo, checkpoint_id)
    if not cp:
        raise CheckpointError(f"no checkpoint {checkpoint_id} for {_repo_key(repo)}")
    commit = str(cp.get("commit", ""))
    if not _SHA_RE.match(commit):                       # defend against a tampered/injected registry record
        raise CheckpointError(f"checkpoint {checkpoint_id} has a non-sha commit ref — refusing to restore")
    r = subprocess.run(["git", "-C", os.path.abspath(repo), "worktree", "add", "--quiet", "--detach",
                        dest, commit], capture_output=True, text=True)
    if r.returncode != 0:
        raise CheckpointError(f"restore failed: {r.stderr.strip()[:200]}")
    return cp


def record_failure(repo, *, broken_patch_sha, failure_reason, affected_modules=None,
                   triggered_by="", rollback_to=None):
    """ASRS failure forensics: what broke, why, which request caused it, and the rollback target.
    Hash-chained. Returns the record (the loop also feeds this forward via Tripartite Memory L2)."""
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": _repo_key(repo), "repo_path": os.path.abspath(repo),
        "broken_patch_sha": str(broken_patch_sha or ""),
        "failure_reason": str(failure_reason)[:300], "affected_modules": list(affected_modules or [])[:50],
        "triggered_by": str(triggered_by)[:300],
        "rollback_to": rollback_to if rollback_to is not None else (last_healthy(repo) or {}).get("id"),
        "actor": "checkpoint-engine",
    }
    return _append_chained(FAILURES, rec)


def verify_chain(path=None):
    """Validate the hash-chain of a registry (checkpoints by default). Returns (ok: bool, detail: str)."""
    path = path or LEDGER
    prev = "0" * 16
    for i, rec in enumerate(_read(path)):
        body = {k: rec[k] for k in rec if k not in ("prev", "h")}
        if rec.get("prev") != prev:
            return False, f"prev mismatch at record {i}"
        if rec.get("h") != _sha(prev + _canonical(body)):
            return False, f"hash mismatch at record {i}"
        prev = rec["h"]
    return True, "ok"


# ---------------- self-test (real git, no network/LLM) ----------------
def _selftest():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="seif-cp-")
    global LEDGER, FAILURES
    LEDGER = os.path.join(tmp, "checkpoints.jsonl")
    FAILURES = os.path.join(tmp, "failures.jsonl")
    repo = os.path.join(tmp, "repo")
    g = lambda *a: subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                  check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", repo], check=True)
    open(os.path.join(repo, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
    g("add", "-A"); g("commit", "-qm", "v1")
    c1 = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    # proof-gating: cannot checkpoint an unverified state
    for bad in (None, {}, {"outcome": "fail", "receipt": "x"}, {"outcome": "pass"}):
        try:
            create(repo, "bad", commit=c1, proof=bad); raise AssertionError(f"accepted bad proof {bad}")
        except CheckpointError:
            pass
    try:
        create(repo, "nocommit", commit="", proof={"outcome": "pass", "receipt": "r1"})
        raise AssertionError("accepted empty commit")
    except CheckpointError:
        pass

    # a verified checkpoint registers + is the last_healthy
    cp1 = create(repo, "add() works", commit=c1, proof={"outcome": "pass", "receipt": "r1", "exit_code": 0},
                 context={"task": "impl add", "files_changed": ["calc.py"]})
    assert last_healthy(repo)["id"] == cp1["id"]
    assert len(lineage(repo)) == 1

    # a second verified state, chained to the first
    open(os.path.join(repo, "calc.py"), "a").write("def sub(a, b):\n    return a - b\n")
    g("add", "-A"); g("commit", "-qm", "v2")
    c2 = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    cp2 = create(repo, "sub() added", commit=c2, proof={"outcome": "pass", "receipt": "r2"},
                 parent=cp1["id"])
    assert last_healthy(repo)["id"] == cp2["id"] and cp2["parent"] == cp1["id"]
    assert [c["id"] for c in lineage(repo)] == [cp1["id"], cp2["id"]]

    # an UNHEALTHY checkpoint is not the rollback target
    cp3 = create(repo, "wip", commit=c2, proof={"outcome": "pass", "receipt": "r3"}, healthy=False)
    assert last_healthy(repo)["id"] == cp2["id"], "unhealthy must not become last_healthy"

    # restore: materialize cp1's verified commit into a fresh worktree
    dest = os.path.join(tmp, "restored")
    restore(repo, cp1["id"], dest)
    body = open(os.path.join(dest, "calc.py")).read()
    assert "def add" in body and "def sub" not in body, "restored the cp1 state (v1, no sub)"

    # ASRS forensics record + default rollback target = last_healthy
    f = record_failure(repo, broken_patch_sha="deadbeef", failure_reason="type error in sub",
                       affected_modules=["calc.py"], triggered_by="add multiply")
    assert f["rollback_to"] == cp2["id"] and f["repo"] == _repo_key(repo)

    # hash chains verify, and tamper is detected
    assert verify_chain()[0] and verify_chain(FAILURES)[0]
    lines = open(LEDGER).read().splitlines()
    rec0 = json.loads(lines[0]); rec0["label"] = "TAMPERED"
    lines[0] = json.dumps(rec0); open(LEDGER, "w").write("\n".join(lines) + "\n")
    assert not verify_chain()[0], "tamper must break the chain"

    print("checkpoint engine selftest PASS")
    print(f"  proof-gated create · lineage {[c['label'] for c in [cp1, cp2]]} · last_healthy=cp2 · "
          f"restore=cp1 state · ASRS rollback_to={f['rollback_to']} · chain tamper-evident")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: checkpoint.py --selftest   |   import: from logos import checkpoint")
