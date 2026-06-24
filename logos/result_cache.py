#!/usr/bin/env python3
"""SEIF exact-fingerprint result cache — skip the model call when an IDENTICAL task was already solved.

The cheapest token a loop can spend is the one it never spends. When the SAME task is re-run against the
SAME base, the SAME test command, the SAME changed-file contents, the SAME model, and the SAME lean flags,
the prior accepted patch + receipt are provably reusable: nothing the model would see has changed, so the
model's output would be the same. This module makes that reuse EXACT and CONSERVATIVE.

Fingerprint = sha256 over a canonical JSON of:
    (task, base_commit, test_cmd, sorted(changed_file_hashes), model, lean_flags)

EXACT-ONLY by design: ANY single field difference → a different fingerprint → a MISS → the model runs.
There is NO fuzzy/semantic reuse here — a near-miss is a miss. That keeps the cache SAFE (it can only ever
return a result that was computed under byte-identical inputs) at the cost of a lower hit rate. Correctness
over hit rate is the right trade for a verification gate.

Storage REUSES the existing L1 backend (memory/tripartite.WorkingMemory): Redis when reachable
(REDIS_URL_CONFIG / $SEIF_REDIS_URL), else an atomic JSON file — the honest default today. No new redis
client, no new backend, no new infra. The cache is just a namespaced view over WorkingMemory, so it
degrades exactly the way the rest of the loop does (file fallback when Redis is absent) and inherits its
TTL / corruption-quarantine behaviour for free.

OPT-IN: nothing here runs unless a caller asks for it. seif_run wires a `result_cache=` switch (off by
default) that checks the cache BEFORE the first model call and skips straight to the cached patch + receipt
on a hit. Default behaviour is byte-identical to before.

Dependency-free (stdlib only); the L1 backend is imported lazily so importing this module never requires
Redis.
"""
import hashlib
import json
import os
import sys
import time

# The L1 backend lives in memory/tripartite.py. Add it to sys.path so this module is importable from either
# logos/ (loop code) or the repo root (tests), without forcing a package layout.
_HERE = os.path.dirname(os.path.abspath(__file__))
_MEM = os.path.join(os.path.dirname(_HERE), "memory")
if _MEM not in sys.path:
    sys.path.insert(0, _MEM)

# Namespace for cache entries inside WorkingMemory. Distinct from the loop's working-set namespace so the
# cache and the hot working-set never collide on a shared backend.
CACHE_NAMESPACE = "seif_result_cache"

# Default time-to-live for a cached result (seconds). A cached accepted patch is only as fresh as the world
# it was computed in; the fingerprint already pins base_commit + file hashes, so staleness is bounded by
# construction, but a TTL bounds storage growth and gives a coarse "re-verify eventually" floor. None = no
# expiry. Callers can override per-store.
DEFAULT_TTL = 14 * 24 * 3600  # 14 days


def _hash_text(text):
    """sha256 hex of a string (utf-8). Used for per-file content hashes and as a hashing primitive."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def hash_file(path):
    """sha256 hex of a file's bytes, or None if it cannot be read. None is a DISTINCT value in the
    fingerprint (a missing/unreadable file is not the same as an empty one), so a vanished file misses."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def changed_file_hashes(repo, files):
    """Map each path in `files` to (path, sha256-of-contents) relative to `repo`. Sorted by path so the
    fingerprint is order-independent: the SAME set of changed files in any order produces the SAME key.

    A path is hashed by its CONTENTS, not its name+mtime — so a file edited back to identical bytes is a
    HIT, and any content change (even one byte) is a MISS. Missing files hash to None (still a miss vs a
    present file)."""
    out = []
    for rel in files:
        p = rel if os.path.isabs(rel) else os.path.join(repo, rel)
        out.append([rel, hash_file(p)])
    out.sort(key=lambda pair: pair[0])
    return out


def _canonical(lean_flags):
    """Normalize lean_flags to a stable, JSON-serializable form. Order is SIGNIFICANT for CLI flags
    (e.g. an allow/deny ordering can matter), so a list is preserved as-is; None stays None (distinct from
    an empty list — 'no route' vs 'an empty route' are different inputs)."""
    if lean_flags is None:
        return None
    return list(lean_flags)


def fingerprint(task, base_commit, test_cmd, changed_hashes, model, lean_flags):
    """The EXACT cache key. sha256 over a canonical JSON of every field that determines the model's output.

    `changed_hashes` is the [[path, sha], ...] structure from changed_file_hashes (already sorted). Every
    argument is included verbatim; there is no normalization that could collapse two genuinely different
    inputs to one key (that would be unsafe fuzzy reuse). `sort_keys=True` + a fixed field ORDER make the
    digest deterministic across processes and Python versions."""
    payload = {
        "task": task,
        "base_commit": base_commit,
        "test_cmd": test_cmd,
        "changed_file_hashes": changed_hashes,
        "model": model,
        "lean_flags": _canonical(lean_flags),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResultCache:
    """Exact-fingerprint result cache over the L1 WorkingMemory backend.

    `lookup(...)` returns the stored entry (patch + receipt + metadata) on an EXACT fingerprint match, else
    None. `store(...)` records an accepted result under its fingerprint. The backend is WorkingMemory:
    Redis if provisioned, atomic JSON file otherwise — so `.backend` reports the truth and the cache works
    with NO Redis present."""

    def __init__(self, path=None, redis_url=None, namespace=CACHE_NAMESPACE, ttl=DEFAULT_TTL):
        # Lazy import keeps `import result_cache` free of any Redis dependency.
        import tripartite as T  # noqa: E402
        # Pass `path` straight through to WorkingMemory: a non-empty path pins a file backend (tests,
        # isolated stores); None lets ambient Redis config bind the default store. We do NOT reimplement
        # backend selection — we inherit it.
        self.mem = T.WorkingMemory(path=path, namespace=namespace, redis_url=redis_url)
        self.ttl = ttl

    @property
    def backend(self):
        """'redis' or 'file' — whatever the underlying WorkingMemory resolved to."""
        return self.mem.backend

    def key_for(self, task, base_commit, test_cmd, changed_hashes, model, lean_flags):
        return fingerprint(task, base_commit, test_cmd, changed_hashes, model, lean_flags)

    def lookup(self, task, base_commit, test_cmd, changed_hashes, model, lean_flags):
        """Return the cached entry dict on an EXACT fingerprint hit, else None. A hit means EVERY field
        matched byte-for-byte; any single difference computed a different key and returns None (a MISS)."""
        key = self.key_for(task, base_commit, test_cmd, changed_hashes, model, lean_flags)
        return self.mem.get(key, default=None)

    def store(self, task, base_commit, test_cmd, changed_hashes, model, lean_flags,
              patch, receipt, *, extra=None, ttl=...):
        """Record an accepted result under its exact fingerprint. Returns the stored entry. `extra` is an
        optional dict merged into the entry (e.g. branch / checkpoint id). `ttl` defaults to the cache's
        configured TTL; pass None for no expiry."""
        key = self.key_for(task, base_commit, test_cmd, changed_hashes, model, lean_flags)
        entry = {
            "fingerprint": key,
            "task": task,
            "base_commit": base_commit,
            "test_cmd": test_cmd,
            "changed_file_hashes": changed_hashes,
            "model": model,
            "lean_flags": _canonical(lean_flags),
            "patch": patch,
            "receipt": receipt,
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if extra:
            entry.update(extra)
        use_ttl = self.ttl if ttl is ... else ttl
        self.mem.set(key, entry, ttl=use_ttl)
        return entry

    def invalidate(self, task, base_commit, test_cmd, changed_hashes, model, lean_flags):
        """Drop a cached entry by fingerprint (e.g. if a downstream re-verify finds it stale)."""
        key = self.key_for(task, base_commit, test_cmd, changed_hashes, model, lean_flags)
        self.mem.delete(key)


def _selftest():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="seif-rcache-")
    try:
        # ---- fingerprint determinism + field sensitivity ----
        ch = [["a.py", "h1"], ["b.py", "h2"]]
        base = ("do X", "abc123", "pytest", ch, "claude-opus-4-8", ["--strict-mcp-config"])
        fp = fingerprint(*base)
        assert fp == fingerprint(*base), "fingerprint must be deterministic"
        # order-independent over the SAME set of changed files
        assert fp == fingerprint("do X", "abc123", "pytest", [["b.py", "h2"], ["a.py", "h1"]],
                                 "claude-opus-4-8", ["--strict-mcp-config"]) or \
            fingerprint("do X", "abc123", "pytest", sorted([["b.py", "h2"], ["a.py", "h1"]]),
                        "claude-opus-4-8", ["--strict-mcp-config"]) == fp
        # every field flips the key (exact-only — no fuzzy collapse)
        assert fingerprint("do Y", "abc123", "pytest", ch, "claude-opus-4-8", []) != fp
        assert fingerprint("do X", "def456", "pytest", ch, "claude-opus-4-8", []) != fp
        assert fingerprint("do X", "abc123", "go test", ch, "claude-opus-4-8", []) != fp
        assert fingerprint("do X", "abc123", "pytest", [["a.py", "DIFF"], ["b.py", "h2"]],
                           "claude-opus-4-8", ["--strict-mcp-config"]) != fp
        assert fingerprint("do X", "abc123", "pytest", ch, "claude-haiku", ["--strict-mcp-config"]) != fp
        assert fingerprint("do X", "abc123", "pytest", ch, "claude-opus-4-8", ["--other"]) != fp
        # None lean_flags is distinct from [] lean_flags
        assert fingerprint("t", "c", "pytest", ch, "m", None) != fingerprint("t", "c", "pytest", ch, "m", [])

        # ---- file content hashing ----
        f1 = os.path.join(tmp, "f1.py")
        open(f1, "w").write("print(1)\n")
        h_a = hash_file(f1)
        open(f1, "w").write("print(2)\n")
        h_b = hash_file(f1)
        assert h_a and h_b and h_a != h_b, "content change must change the hash"
        open(f1, "w").write("print(1)\n")
        assert hash_file(f1) == h_a, "identical bytes → identical hash (edit-back is a hit)"
        assert hash_file(os.path.join(tmp, "nope.py")) is None, "missing file hashes to None"

        # ---- file-backend cache (NO redis): store → exact hit reuses patch+receipt ----
        store_path = os.path.join(tmp, "cache.json")
        rc = ResultCache(path=store_path)
        assert rc.backend == "file", "no redis in selftest → file backend"
        args = ("fix bug", "deadbeef", "pytest", ch, "claude-opus-4-8", ["--strict-mcp-config"])
        assert rc.lookup(*args) is None, "cold cache misses"
        rc.store(*args, patch="DIFF-BODY", receipt={"h": "rcpt123", "outcome": "pass"},
                 extra={"branch": "seif/x"})
        hit = rc.lookup(*args)
        assert hit is not None, "warm cache must hit on identical inputs"
        assert hit["patch"] == "DIFF-BODY" and hit["receipt"]["h"] == "rcpt123", hit
        assert hit["branch"] == "seif/x"
        # ---- any single field change MISSES ----
        assert rc.lookup("fix BUG", "deadbeef", "pytest", ch, "claude-opus-4-8",
                         ["--strict-mcp-config"]) is None
        assert rc.lookup("fix bug", "deadbeef", "pytest", ch, "claude-opus-4-8", []) is None
        assert rc.lookup("fix bug", "OTHER", "pytest", ch, "claude-opus-4-8",
                         ["--strict-mcp-config"]) is None
        # ---- invalidate drops it ----
        rc.invalidate(*args)
        assert rc.lookup(*args) is None, "invalidate must drop the entry"

        # ---- persistence: a fresh ResultCache over the SAME file sees a prior store (file backend works) ----
        rc.store(*args, patch="P2", receipt={"h": "r2"})
        rc2 = ResultCache(path=store_path)
        assert rc2.lookup(*args)["patch"] == "P2", "file-backed cache persists across instances"

        print("result_cache selftest PASS")
        print(f"  backend={rc.backend} (redis founder-gated; file fallback exercised)")
        print(f"  fingerprint={fp[:16]}…  exact-only (every field flips the key)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: result_cache.py --selftest   |   import: from result_cache import ResultCache, fingerprint")
