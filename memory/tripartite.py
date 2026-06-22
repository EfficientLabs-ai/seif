#!/usr/bin/env python3
"""SEIF Tripartite Memory v1 — the STATE layer of the autonomous loop ("never forgets").

Three layers, each degrading gracefully so the loop runs with whatever infrastructure exists today:

  L1  WorkingMemory  — hot working-set KV with TTL.  Redis if available, else an atomic JSON file.
                       (Redis is founder/sudo-gated; the file backend is the honest default today.)
  L2  EpisodicMemory — append-only JSONL of typed trajectory summaries (attempts/receipts/lessons).
                       This is the durable record the loop replays to reconstruct "what was tried".
                       A Postgres adapter can drop in later; file-first per the directive (no new infra
                       unless measured need).
  L3  SemanticMemory — read-only over a repo's `graphify-out/graph.json` (NetworkX node-link). Answers
                       "what does changing this file touch?" deterministically (no LLM), plus an
                       LLM-backed natural-language `query()` that shells out to the `graphify` CLI.

Facade `Memory` ties them together and adds `continuity_snapshot()` — the ECP tie-in that lets a
resumed/looped session reconstruct state from the ledger + episodes instead of the transcript.

Claim discipline: L1 today = FILE backend (Redis not installed). L3 today covers only repos that have a
`graphify-out/` (efficientlabs-web does; others must be built first via `SemanticMemory.build`). Nothing
here is claimed beyond what the backend actually provides — `.backend` / `.available` report the truth.

Dependency-free (stdlib only). `redis` and `psycopg` are imported lazily and optionally.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import deque

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "store")

# trajectory_summary lives in logos/; reuse its validator for L2 records when summaries are passed.
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "logos"))
try:
    import trajectory_summary as TS   # noqa: E402
except Exception:                     # noqa: BLE001
    TS = None


def _atomic_write(path, text):
    """Write+rename so a reader never sees a half-written file (single-host loop safety)."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ----------------------------------------------------------------------------- L1
class WorkingMemory:
    """Hot working-set KV with optional TTL. Redis if reachable, else an atomic JSON file."""

    def __init__(self, path=None, namespace="seif", redis_url=None):
        self.namespace = namespace
        self.path = path or os.path.join(STORE, "working.json")
        self._r = None
        self.backend = "file"
        url = redis_url or os.environ.get("SEIF_REDIS_URL")
        if url:
            try:
                import redis  # noqa: F401  (optional)
                self._r = redis.Redis.from_url(url, socket_connect_timeout=0.5, decode_responses=True)
                self._r.ping()
                self.backend = "redis"
            except Exception:  # noqa: BLE001  — degrade to file, never crash the loop
                self._r = None
                self.backend = "file"

    def _k(self, key):
        return f"{self.namespace}:{key}"

    # ---- file backend helpers (keys stored NAMESPACED, like the Redis path; expiry lazy on read) ----
    def _load(self):
        """Return the store dict. Missing file → {} (normal). CORRUPT file → quarantine it and warn
        LOUDLY, then start fresh — so corruption is never silently swallowed as 'empty state'."""
        try:
            with open(self.path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as e:
            bad = f"{self.path}.corrupt-{int(time.time())}"
            try:
                os.replace(self.path, bad)
            except OSError:
                bad = "(could not quarantine)"
            sys.stderr.write(f"[working-memory] CORRUPT store {self.path} ({e!r}); quarantined to {bad}, "
                             "starting fresh\n")
            return {}

    def _save(self, d):
        _atomic_write(self.path, json.dumps(d))

    def set(self, key, value, ttl=None):
        if self._r is not None:
            self._r.set(self._k(key), json.dumps(value), ex=int(ttl) if ttl else None)
            return
        d = self._load()
        d[self._k(key)] = {"v": value, "exp": (time.time() + ttl) if ttl else None}
        self._save(d)

    def get(self, key, default=None):
        if self._r is not None:
            raw = self._r.get(self._k(key))
            return json.loads(raw) if raw is not None else default
        d = self._load()
        rec = d.get(self._k(key))
        if rec is None:
            return default
        if rec.get("exp") is not None and time.time() > rec["exp"]:
            d.pop(self._k(key), None)
            self._save(d)
            return default
        return rec["v"]

    def delete(self, key):
        if self._r is not None:
            self._r.delete(self._k(key))
            return
        d = self._load()
        if d.pop(self._k(key), None) is not None:
            self._save(d)

    def keys(self, prefix=""):
        pre = len(self.namespace) + 1  # strip "namespace:" on output
        if self._r is not None:
            return sorted(k[pre:] for k in self._r.scan_iter(match=self._k(prefix) + "*"))
        d = self._load()
        now = time.time()
        full = self._k(prefix)
        return sorted(k[pre:] for k, rec in d.items()
                      if k.startswith(full) and not (rec.get("exp") and now > rec["exp"]))


# ----------------------------------------------------------------------------- L2
class EpisodicMemory:
    """Append-only JSONL of typed trajectory summaries — the durable 'what was tried' record."""

    def __init__(self, path=None):
        self.path = path or os.path.join(STORE, "episodes.jsonl")

    def record(self, summary, *, validate=True):
        """Append a trajectory summary (see logos/trajectory_summary.py). Returns the stored record."""
        if validate and TS is not None:
            TS.validate(summary)  # raises SummaryError on a malformed summary — fail loud, not silent
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "summary": summary}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def _iter(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue  # tolerate a torn final line; never crash a recall

    def query(self, *, task_id=None, termination=None, since=None, limit=None):
        """Filter episodes (newest first). `since` = ISO ts string lower bound (inclusive)."""
        out = []
        for rec in self._iter():
            s = rec.get("summary", {})
            if task_id is not None and s.get("task_id") != task_id:
                continue
            if termination is not None and s.get("termination_reason") != termination:
                continue
            if since is not None and rec.get("ts", "") < since:
                continue
            out.append(rec)
        out.reverse()
        return out[:limit] if limit else out

    def recent(self, n=10):
        return self.query(limit=n)

    def reusable_lessons(self, limit=None):
        """Episodes whose summary passes the trajectory_summary reuse filter (accepted + lesson + clean)."""
        out = [r for r in self.query() if TS and TS.is_reusable(r.get("summary", {}))]
        return out[:limit] if limit else out


# ----------------------------------------------------------------------------- L3
_IMPORT_RELATIONS = {"imports_from", "imports", "import", "depends_on", "requires", "uses", "calls"}


class SemanticMemory:
    """Read-only view over a repo's graphify-out/graph.json. Deterministic impact/dependency queries
    plus an optional LLM-backed natural-language query via the `graphify` CLI."""

    def __init__(self, repo):
        self.repo = os.path.abspath(repo)
        self.out_dir = os.path.join(self.repo, "graphify-out")
        self.graph_path = os.path.join(self.out_dir, "graph.json")
        self.available = os.path.exists(self.graph_path)
        self._g = None
        self._by_file = None
        self._by_id = None
        self._fwd = None
        self._rev = None

    # ---- loading / indexing (lazy, never raises into the loop) ----
    def _ensure(self):
        if self._by_id is not None:   # already indexed (possibly to an empty/degraded state)
            return
        self._g, self._by_id, self._by_file, self._fwd, self._rev = {}, {}, {}, {}, {}
        if not self.available:
            return
        try:
            with open(self.graph_path) as f:
                self._g = json.load(f)
        except (OSError, ValueError) as e:   # missing/unreadable/corrupt graph → degrade, don't crash
            sys.stderr.write(f"[semantic] graph load failed ({self.graph_path}): {e!r}; degrading\n")
            self.available = False
            self._g = {}
            return
        for n in self._g.get("nodes", []):
            nid = n.get("id")
            if nid is None:
                continue
            self._by_id[nid] = n
            if n.get("source_file"):
                self._by_file.setdefault(n["source_file"], []).append(nid)
        for e in self._g.get("links", []):
            s, t, rel = e.get("source"), e.get("target"), e.get("relation")
            if s is None or t is None:
                continue
            self._fwd.setdefault(s, []).append((t, rel))
            self._rev.setdefault(t, []).append((s, rel))

    @property
    def built_at_commit(self):
        self._ensure()
        return self._g.get("built_at_commit") if self._g else None

    def is_stale(self):
        """True if the graph was built at a different commit than the repo's current HEAD (or unknown)."""
        if not self.available:
            return True
        head = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        return not head or head != self.built_at_commit

    def _ids_for(self, file_or_id):
        """Resolve a query target to node ids: exact id, exact source_file, or basename match."""
        self._ensure()
        if file_or_id in self._by_id:
            return [file_or_id]
        if file_or_id in self._by_file:
            return list(self._by_file[file_or_id])
        base = os.path.basename(file_or_id)
        ids = [i for sf, ids in self._by_file.items() if os.path.basename(sf) == base for i in ids]
        return ids

    def _walk(self, file_or_id, direction, relations, depth):
        self._ensure()
        adjacency = self._rev if direction == "rev" else self._fwd
        seen, files, frontier = set(), set(), deque((i, 0) for i in self._ids_for(file_or_id))
        for i, _ in list(frontier):
            seen.add(i)
        while frontier:
            nid, d = frontier.popleft()
            if d >= depth:
                continue
            for nxt, rel in adjacency.get(nid, []):
                if relations and rel not in relations:
                    continue
                if nxt not in seen:
                    seen.add(nxt)
                    n = self._by_id.get(nxt, {})
                    if n.get("source_file"):
                        files.add(n["source_file"])
                    frontier.append((nxt, d + 1))
        return sorted(files)

    def impact(self, file_or_id, depth=3):
        """Reverse import closure: which source files DEPEND ON the target → 'what does changing this touch?'"""
        return self._walk(file_or_id, "rev", _IMPORT_RELATIONS, depth)

    def dependencies(self, file_or_id, depth=3):
        """Forward import closure: which source files the target DEPENDS ON."""
        return self._walk(file_or_id, "fwd", _IMPORT_RELATIONS, depth)

    def neighbors(self, file_or_id):
        """Immediate graph neighbours (both directions, any relation) as (id, relation, direction)."""
        self._ensure()
        out = []
        for i in self._ids_for(file_or_id):
            out += [(t, rel, "out") for t, rel in self._fwd.get(i, [])]
            out += [(s, rel, "in") for s, rel in self._rev.get(i, [])]
        return out

    def path(self, a, b):
        """Shortest undirected path of node ids between two targets, or [] if none."""
        self._ensure()
        starts, goals = sorted(set(self._ids_for(a))), set(self._ids_for(b))
        if not starts or not goals:
            return []
        prev, q = {s: None for s in starts}, deque(starts)
        while q:
            cur = q.popleft()
            if cur in goals:
                chain = [cur]
                while prev[chain[-1]] is not None:
                    chain.append(prev[chain[-1]])
                return list(reversed(chain))
            for nxt, _ in self._fwd.get(cur, []) + self._rev.get(cur, []):
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
        return []

    def query(self, question, budget=1500, timeout=120):
        """LLM-backed natural-language query via the `graphify` CLI (cwd = repo). Returns stdout text.
        Falls back to a clear message if the CLI is absent — never raises into the loop."""
        cli = os.path.expanduser("~/.local/bin/graphify")
        if not (self.available and os.path.exists(cli)):
            return f"[semantic] no graphify query available (graph={self.available}, cli={os.path.exists(cli)})"
        try:
            p = subprocess.run([cli, "query", question, "--budget", str(budget)],
                               cwd=self.repo, capture_output=True, text=True, timeout=timeout)
            return (p.stdout or p.stderr).strip()
        except subprocess.TimeoutExpired:
            return "[semantic] graphify query timed out"

    @staticmethod
    def build(repo, mode=None, timeout=1800):
        """Build (or --update) graphify-out for a repo via the CLI. Returns the rc. NOTE: deep mode and
        first builds may call an LLM — caller decides when to spend that. AST extraction is the core."""
        cli = os.path.expanduser("~/.local/bin/graphify")
        args = [cli, os.path.abspath(repo)]
        if os.path.exists(os.path.join(repo, "graphify-out", "graph.json")):
            args.append("--update")
        if mode:
            args += ["--mode", mode]
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).returncode


# ----------------------------------------------------------------------------- Facade
class Memory:
    """Unified tripartite facade for the loop. `working`/`episodic` are process-wide; `graph(repo)`
    returns a per-repo semantic view (cached)."""

    def __init__(self, ecp_ledger=None):
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory()
        self._graphs = {}
        self.ecp_ledger = ecp_ledger or "/opt/efficient-labs/command-center/06_status/session-ledger.json"

    # L1 / L2 convenience
    def remember(self, key, value, ttl=None):
        self.working.set(key, value, ttl=ttl)

    def recall(self, key, default=None):
        return self.working.get(key, default)

    def record_attempt(self, summary, validate=True):
        return self.episodic.record(summary, validate=validate)

    # L3
    def graph(self, repo):
        key = os.path.abspath(repo)
        if key not in self._graphs:
            self._graphs[key] = SemanticMemory(key)
        return self._graphs[key]

    def continuity_snapshot(self, task_id=None, n_episodes=5, repo=None):
        """Reconstruct 'where am I' for a resumed/looped session WITHOUT the transcript: the ECP session
        ledger (deterministic state) + the most recent episodes + open reuse lessons. The 'never forgets'
        primitive — the loop reads this on boot instead of re-deriving from chat.

        When `repo` is given, also surface the L4 checkpoint state for that repo (last healthy rollback
        target + lineage length). A missing/broken checkpoint module degrades to None/0 and NEVER breaks
        continuity. When `repo` is None, behaviour and return keys are unchanged."""
        ecp = None
        try:
            with open(self.ecp_ledger) as f:
                ecp = json.load(f)
        except (OSError, ValueError):
            ecp = None
        eps = self.episodic.query(task_id=task_id, limit=n_episodes)
        snap = {
            "working_keys": self.working.keys(),
            "recent_episodes": eps,
            "reusable_lessons": self.episodic.reusable_lessons(limit=n_episodes),
            "ecp_ledger_present": ecp is not None,
            "ecp_ledger_keys": list(ecp.keys())[:20] if isinstance(ecp, dict) else None,
            "l1_backend": self.working.backend,
        }
        if repo is not None:
            # L4 checkpoint engine lives in logos/ (already on sys.path for trajectory_summary). Any
            # failure here degrades to None/0 — checkpoint state is additive, never a continuity blocker.
            last_healthy, count = None, 0
            try:
                import checkpoint as CP  # noqa: E402
                last_healthy = CP.last_healthy(repo) or None
                count = len(CP.lineage(repo))
            except Exception:  # noqa: BLE001 — missing/broken checkpoint module must not break continuity
                last_healthy, count = None, 0
            snap["last_healthy_checkpoint"] = last_healthy
            snap["checkpoint_count"] = count
        return snap


# ----------------------------------------------------------------------------- selftest
def _selftest():
    import shutil
    tmp = tempfile.mkdtemp(prefix="seif-mem-")
    try:
        # ---- L1: set/get/ttl/delete/keys on the file backend ----
        wm = WorkingMemory(path=os.path.join(tmp, "w.json"))
        assert wm.backend == "file", "no redis in selftest → file backend"
        wm.set("cur_task", {"id": "t1", "step": 2})
        assert wm.get("cur_task")["step"] == 2
        wm.set("ephemeral", 1, ttl=-1)             # already expired
        assert wm.get("ephemeral", "gone") == "gone", "ttl expiry enforced on read"
        wm.set("a", 1); wm.set("ab", 2)
        assert wm.keys("a") == ["a", "ab"], wm.keys("a")
        wm.delete("a"); assert wm.get("a") is None
        assert wm.get("missing", 42) == 42

        # ---- L2: record + query + reuse filter ----
        em = EpisodicMemory(path=os.path.join(tmp, "ep.jsonl"))
        s_ok = TS.build_summary("att1", "task_x", "fix cache key", "accepted",
                                files_changed=["a.py"], evidence_passed=["L2"],
                                reusable_lesson_candidate="resolve paths before keying")
        s_bad = TS.build_summary("att2", "task_x", "narrow fix", "rejected",
                                 evidence_failed=["L2"], prohibited_reuse_reasons=["overfit"])
        em.record(s_ok); em.record(s_bad)
        assert len(em.query(task_id="task_x")) == 2
        assert len(em.query(termination="accepted")) == 1
        assert em.recent(1)[0]["summary"]["attempt_id"] == "att2", "newest first"
        lessons = em.reusable_lessons()
        assert len(lessons) == 1 and lessons[0]["summary"]["attempt_id"] == "att1"
        try:
            em.record({"not": "a valid summary"}); raise AssertionError("malformed summary accepted")
        except TS.SummaryError:
            pass

        # ---- L3: deterministic graph queries on a synthetic graphify-out ----
        repo = os.path.join(tmp, "repo")
        gdir = os.path.join(repo, "graphify-out")
        os.makedirs(gdir)
        graph = {
            "directed": False, "nodes": [
                {"id": "core", "source_file": "src/core.py", "label": "core.py"},
                {"id": "mid", "source_file": "src/mid.py", "label": "mid.py"},
                {"id": "app", "source_file": "src/app.py", "label": "app.py"},
                {"id": "loner", "source_file": "src/loner.py", "label": "loner.py"},
            ],
            "links": [
                {"source": "mid", "target": "core", "relation": "imports_from"},  # mid imports core
                {"source": "app", "target": "mid", "relation": "imports_from"},   # app imports mid
            ],
            "built_at_commit": "deadbeef",
        }
        json.dump(graph, open(os.path.join(gdir, "graph.json"), "w"))
        sm = SemanticMemory(repo)
        assert sm.available
        # who depends on core? mid (direct) and app (transitive) → both touched by a core change
        imp = sm.impact("src/core.py")
        assert imp == ["src/app.py", "src/mid.py"], imp
        # depth=1 stops at direct dependents
        assert sm.impact("src/core.py", depth=1) == ["src/mid.py"], sm.impact("src/core.py", depth=1)
        # what does app depend on? mid + core
        assert sm.dependencies("src/app.py") == ["src/core.py", "src/mid.py"], sm.dependencies("src/app.py")
        # loner touches nothing
        assert sm.impact("src/loner.py") == [] and sm.dependencies("src/loner.py") == []
        # path app→core exists; basename resolution works
        assert sm.path("app.py", "core.py") == ["app", "mid", "core"], sm.path("app.py", "core.py")
        assert sm.built_at_commit == "deadbeef"
        # query falls back gracefully (no real graphify in a synthetic repo path is fine either way)
        q = sm.query("anything")
        assert isinstance(q, str)

        # ---- L3 graceful degrade: repo with NO graphify-out must NOT crash the loop ----
        empty_repo = os.path.join(tmp, "empty_repo")
        os.makedirs(empty_repo)
        sm0 = SemanticMemory(empty_repo)
        assert sm0.available is False
        assert sm0.impact("anything.py") == [] and sm0.dependencies("x.py") == []
        assert sm0.neighbors("x") == [] and sm0.path("a", "b") == []
        assert sm0.built_at_commit is None and sm0.is_stale() is True
        # ---- L3 corrupt graph.json degrades (available flips False) instead of throwing ----
        bad_repo = os.path.join(tmp, "bad_repo")
        os.makedirs(os.path.join(bad_repo, "graphify-out"))
        open(os.path.join(bad_repo, "graphify-out", "graph.json"), "w").write("{not json")
        smb = SemanticMemory(bad_repo)
        assert smb.available is True               # file exists pre-load
        assert smb.impact("x.py") == []            # load fails inside _ensure → degrade
        assert smb.available is False              # flipped after the failed load

        # ---- L1 namespace isolation: two namespaces over the SAME file must not collide ----
        shared = os.path.join(tmp, "shared.json")
        a_ns = WorkingMemory(path=shared, namespace="ns_a")
        b_ns = WorkingMemory(path=shared, namespace="ns_b")
        a_ns.set("k", "from_a"); b_ns.set("k", "from_b")
        assert a_ns.get("k") == "from_a" and b_ns.get("k") == "from_b", "namespaces must not collide"
        assert a_ns.keys() == ["k"] and b_ns.keys() == ["k"]   # keys() strips the namespace
        # ---- L1 corrupt store is quarantined + warned, not silently treated as empty-then-clobbered ----
        corrupt = os.path.join(tmp, "corrupt.json")
        open(corrupt, "w").write("{garbage")
        cm = WorkingMemory(path=corrupt)
        assert cm.get("anything") is None          # corruption handled, fresh start
        assert any(f.startswith("corrupt.json.corrupt-") for f in os.listdir(tmp)), "bad store quarantined"

        # ---- Facade + continuity ----
        mem = Memory(ecp_ledger=os.path.join(tmp, "nope.json"))  # missing ledger → present:False
        mem.working = wm; mem.episodic = em
        snap = mem.continuity_snapshot(task_id="task_x", n_episodes=3)
        assert snap["l1_backend"] == "file"
        assert snap["ecp_ledger_present"] is False
        assert len(snap["recent_episodes"]) == 2 and len(snap["reusable_lessons"]) == 1
        g = mem.graph(repo)
        assert g.impact("src/core.py") == ["src/app.py", "src/mid.py"]

        print("tripartite memory selftest PASS")
        print(f"  L1 backend={wm.backend} (redis founder-gated; file fallback exercised)")
        print(f"  L2 episodes={len(em.query())} reusable={len(em.reusable_lessons())}")
        print(f"  L3 impact(core)={imp}  path(app,core)={sm.path('app.py','core.py')}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: tripartite.py --selftest   |   import: from memory.tripartite import Memory")
