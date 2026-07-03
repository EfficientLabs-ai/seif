#!/usr/bin/env python3
"""SEIF two-plane runtime — the persistent CONTROLLER + lean WORKERS (skeleton).

The thesis in one shape: the founder is removed from the *loop* but stays at the *merge gate*. The
controller is the long-lived plane; each worker is a short-lived, minimum-environment plane.

  CONTROLLER (persistent)            WORKER (lean, one-shot)
  ─────────────────────────         ────────────────────────────────────────────
  holds the backlog                 = ONE `seif_run.seif_run()` call …
  holds the route table (01_routes) … with the task's route compiled into lean flags
  holds the memory handles          … and NO extra context (the route IS the minimum env)
  dispatches each task → a worker    returns a receipt {accepted, landed, reason, pr, …}
  collects receipts
  enforces CAPS + an ACCEPT-RATE floor   (← REUSED from seif_loop.run_loop, not re-implemented)
  queues every ACCEPTED+LANDED PR for the founder (← seif_loop already does this; never merges)

WHAT THIS MODULE DOES NOT DO (on purpose): it does not re-implement the gate. The gate = the project's
real test suite (exit code) + the integrity guard, both already inside `seif_run`. Caps + the accept-rate
floor + the founder queue already live in `seif_loop.run_loop` / `run_one`. The controller's only new job
is the TWO-PLANE wiring: pick the route for a task, compile it into the worker's lean operating
environment, and hand the whole backlog to the existing loop with that route-injecting worker.

A WORKER is therefore literally: `seif_run(repo, prompt, test_cmd, route=<compiled>, …)`. The route carries
the lean flags (drop ambient user CLAUDE.md/skills/hooks, scope MCP) + the routed (cheap-default) model +
the turn budget — the per-task "minimum operating environment" (logos/ecp_route.py compiles it).

DRY-RUN: every model/network touch is behind an INJECTABLE `runner`. `Controller(dry_run=True)` (or
`make_dry_runner()`) installs a deterministic fake worker, so the whole control plane — dispatch, caps,
accept-rate floor, founder queue — is exercisable with no LLM and no network (see the smoke test below and
tests/test_controller.py).
"""
import argparse
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "memory"))

import seif_run                       # noqa: E402  — the worker primitive
import seif_loop as SL                # noqa: E402  — caps + accept-rate floor + founder queue (REUSED)
import ecp_route as ECP               # noqa: E402  — route → minimum operating environment
from tripartite import Memory         # noqa: E402

# The route table the controller routes against. Default = the repo's 01_routes/ directory.
DEFAULT_ROUTE_DIR = os.path.join(os.path.dirname(_HERE), "01_routes")


# --------------------------------------------------------------------------- route table
def load_route_table(route_dir=None):
    """Load every `efl.route/v1` manifest under `route_dir` (default 01_routes/). Best-effort: a malformed
    or non-route YAML file is skipped (with a warning), never fatal — one bad route can't sink the plane."""
    route_dir = route_dir or DEFAULT_ROUTE_DIR
    routes, warnings = [], []
    if not os.path.isdir(route_dir):
        return routes, [f"route dir absent: {route_dir}"]
    for path in sorted(glob.glob(os.path.join(route_dir, "*.yaml")) +
                       glob.glob(os.path.join(route_dir, "*.yml"))):
        try:
            r = ECP.load_route(path)
        except Exception as e:  # noqa: BLE001 — a parse error in one file must not break the table
            warnings.append(f"skip {os.path.basename(path)}: load error {e!r}")
            continue
        if not isinstance(r, dict) or r.get("schema") != ECP.SCHEMA:
            warnings.append(f"skip {os.path.basename(path)}: not a {ECP.SCHEMA} route")
            continue
        problems = ECP.validate_route(r)
        if problems:
            warnings.append(f"skip {r.get('id') or os.path.basename(path)}: invalid ({'; '.join(problems)})")
            continue
        routes.append(r)
    return routes, warnings


def _first_path(task):
    """A representative path for route-matching: the first declared path/glob on the task, if any."""
    for k in ("path", "paths", "files"):
        v = task.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, (list, tuple)) and v:
            return v[0]
    return None


# --------------------------------------------------------------------------- the controller
class Controller:
    """Persistent control plane. Construct ONCE, hand it a backlog, call `run()`.

    The controller is long-lived: it owns the backlog, the compiled route table, and the memory handles
    across many dispatches. Each `run()` drives the held backlog through the existing SEIF loop, injecting
    the per-task route into the worker. State that must survive (episodes, receipts, the founder queue)
    lives in Tripartite Memory + the ledger, not on this object.
    """

    def __init__(self, backlog=None, *, routes=None, route_dir=None, mem=None, cfg=None,
                 runner=None, dry_run=False, queue_path=None):
        self.backlog = list(backlog or [])
        if routes is None:
            routes, self.route_warnings = load_route_table(route_dir)
        else:
            self.route_warnings = []
        self.routes = routes
        self.mem = mem or Memory()
        self.cfg = cfg or SL.LoopConfig()
        self.dry_run = dry_run
        # The base worker primitive. dry_run installs a deterministic fake so no model/network is touched.
        self._base_runner = runner or (make_dry_runner() if dry_run else seif_run.seif_run)
        # Optional founder-queue redirect (tests point this at a temp file). seif_loop resolves
        # FOUNDER_QUEUE at call time, so we set it for the duration of run() and restore after.
        self.queue_path = queue_path

    # -- routing ---------------------------------------------------------------
    def route_for(self, task):
        """Pick the route for a task. Explicit `task['route']` (a route id, a manifest dict, or a path)
        wins; otherwise match by intent/path against the loaded table. Returns a route MANIFEST dict (or a
        path/dict the caller supplied), or None when nothing matches (worker runs un-routed = full context)."""
        explicit = task.get("route")
        if isinstance(explicit, dict):
            return explicit
        if isinstance(explicit, str):
            # an id present in the table, else treat as a manifest path for seif_run to load
            for r in self.routes:
                if r.get("id") == explicit:
                    return r
            return explicit
        return ECP.match_route(self.routes, intent=task.get("intent"), path=_first_path(task))

    def compile_for(self, task, changed_files=None):
        """Compile the task's route into the worker's minimum operating environment (lean flags + model +
        budget). Returns the compiled dict, or None if no route applies / a path-only route can't be
        compiled here (seif_run will load+compile it). Pure — no I/O when the route is already a manifest."""
        route = self.route_for(task)
        if route is None or isinstance(route, str):
            return None
        try:
            return ECP.compile_route(route, changed_files=changed_files)
        except Exception:  # noqa: BLE001 — a bad route degrades to un-routed, never crashes dispatch
            return None

    # -- the worker plane ------------------------------------------------------
    def _route_runner(self, route_index=None):
        """Wrap the base worker so each dispatched worker is launched with its task's route compiled into
        lean flags and NO extra context (the route is the minimum env). This is the two-plane seam: the
        controller decides the operating environment; the worker is one `seif_run()` call inside it.

        The returned closure matches the signature `seif_loop.run_one` calls a runner with
        (repo, prompt, test_cmd, budget=, timeout=, make_pr=, [protected=]); it resolves the AUTHORITATIVE
        per-task route and forwards it as `route=` (when the base runner accepts it — the dry-run/fake
        runner ignores the kwarg gracefully via the adapter below).

        `route_index` maps a task body → its `route_for(task)` route, computed up-front in `run()` BEFORE
        the loop strips each task to a prompt. The loop builds `prompt = task["task"] + memory_preface`, so
        the original task body is a PREFIX of the prompt — we look the route up by longest-matching prefix.
        That honors a task's explicit `route` / `intent` / `path` at dispatch time (not just a prompt verb).
        Falls back to prompt-verb inference only when no indexed task matches (e.g. a direct ad-hoc call)."""
        base = self._base_runner
        ctrl = self
        index = route_index or {}

        def runner(repo, prompt, test_cmd, **kw):
            route = ctrl._resolve_dispatch_route(prompt, index)
            return _invoke_worker(base, repo, prompt, test_cmd, route=route, **kw)

        return runner

    def _resolve_dispatch_route(self, prompt, index):
        """Authoritative route for an in-flight worker: the precomputed `route_for(task)` if this prompt
        carries a known task body as its prefix; else prompt-verb inference. Returns a manifest dict / path
        / None to pass straight to `seif_run(route=…)`."""
        p = prompt or ""
        best = None
        for body, route in index.items():
            if body and p.startswith(body) and (best is None or len(body) > len(best[0])):
                best = (body, route)
        # An indexed route (explicit/intent/path) is authoritative when present; only fall back to
        # prompt-verb inference when the task carried no routable signal (route_for → None).
        if best is not None and best[1] is not None:
            return best[1]
        return self._route_for_dispatch(prompt)

    def _route_for_dispatch(self, prompt):
        """Fallback route resolution from the prompt alone (no task identity available). Matches the
        leading-verb intent against the table — best-effort; a structured task→intent field is the real
        binding and is what the `route_index` path uses. Returns a manifest dict / None."""
        return ECP.match_route(self.routes, intent=_infer_intent(prompt), path=None)

    def _build_route_index(self, tasks):
        """Map each task's body → its authoritative `route_for(task)`, so the route-injecting runner can
        honor explicit `route` / `intent` / `path` even though the loop hands the runner only a prompt."""
        index = {}
        for t in tasks:
            body = t.get("task")
            if body:
                index[body] = self.route_for(t)
        return index

    # -- dispatch + run --------------------------------------------------------
    def dispatch(self, task, idx=0):
        """Run ONE task through the gate as a worker, with caps + memory + receipt + founder-queue all
        handled by the REUSED `seif_loop.run_one`. The task's authoritative route (explicit/intent/path)
        is resolved up-front and injected into the worker. Returns the per-task record.

        Same queue_path redirect as `run()`: `run_one` queues a landed task via `SL.FOUNDER_QUEUE`
        resolved at call time, so dispatch() must save/set/restore it too — otherwise a Controller
        constructed with `queue_path=` would still append to the production founder queue here."""
        runner = self._route_runner(self._build_route_index([task]))
        orig_q = SL.FOUNDER_QUEUE
        if self.queue_path:
            SL.FOUNDER_QUEUE = self.queue_path
        try:
            return SL.run_one(task, self.mem, self.cfg, runner=runner, idx=idx)
        finally:
            SL.FOUNDER_QUEUE = orig_q

    def run(self):
        """Drive the whole held backlog through the gate with caps + the accept-rate floor + the founder
        queue — all REUSED from `seif_loop.run_loop`. The only new behavior is the route-injecting worker.
        Returns the loop's cycle summary, augmented with the route-table warnings."""
        index = self._build_route_index(self.backlog)
        orig_q = SL.FOUNDER_QUEUE
        if self.queue_path:
            SL.FOUNDER_QUEUE = self.queue_path
        try:
            summary = SL.run_loop(self.backlog, mem=self.mem, cfg=self.cfg,
                                  runner=self._route_runner(index))
        finally:
            SL.FOUNDER_QUEUE = orig_q
        summary["route_table"] = {"loaded": len(self.routes), "warnings": self.route_warnings}
        summary["dry_run"] = self.dry_run
        return summary

    def founder_queue(self, queue_path=None):
        """Read back what is queued for the founder (accepted + landed PRs). Never merges — read-only."""
        path = queue_path or self.queue_path or SL.FOUNDER_QUEUE
        if not os.path.exists(path):
            return []
        out = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:  # noqa: BLE001 — a corrupt line shouldn't hide the rest of the queue
                        continue
        return out


# --------------------------------------------------------------------------- worker adapter
def _invoke_worker(base, repo, prompt, test_cmd, *, route=None, **kw):
    """Call the base worker, forwarding `route=` only if it accepts it. The real `seif_run.seif_run` takes
    `route=`; a test/dry-run fake may not. This keeps the dry-run path (and arbitrary fakes) compatible
    without forcing every fake to declare a `route` parameter."""
    if route is not None and _accepts_kwarg(base, "route"):
        kw = {**kw, "route": route}
    return base(repo, prompt, test_cmd, **kw)


def _accepts_kwarg(fn, name):
    try:
        import inspect
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    params = sig.parameters.values()
    if any(p.name == name for p in params):
        return True
    return any(p.kind == p.VAR_KEYWORD for p in params)


def _infer_intent(prompt):
    """Map the leading verb of a task prompt to a route intent vocabulary (fix/debug/modify/add/refactor).
    Deliberately tiny — a structured task→intent field is the real binding; this is the skeleton fallback."""
    p = (prompt or "").strip().lower()
    for verb, intent in (("fix", "fix"), ("debug", "debug"), ("modify", "modify"),
                         ("refactor", "refactor"), ("add", "add"), ("implement", "add")):
        if p.startswith(verb):
            return intent
    return None


# --------------------------------------------------------------------------- dry-run fake worker
def make_dry_runner(outcomes=None):
    """A deterministic fake worker for dry-runs and tests — NO model, NO network. Outcome is chosen by a
    keyword in the task prompt so a backlog can script accept/reject/integrity/throw deterministically:

        ACCEPT     → accepted + landed (queues for the founder)
        NOLAND     → accepted but push/PR failed (NOT landed → NOT queued)
        INTEGRITY  → integrity_violation (rejected, recorded with a prohibition)
        BOOM       → raises (must be contained by run_one)
        (default)  → tests failed (rejected)

    Pass `outcomes` to override the keyword→result map. The runner accepts (and ignores) **kw including
    `route`, so the controller's route-injecting wrapper drives it unchanged."""
    table = outcomes or {
        "ACCEPT": {"accepted": True, "reason": "verified", "landed": True, "pr": "http://pr/dry",
                   "receipt": {"h": "dry-accept"}, "patch": "diff --git a/src.py b/src.py\n+x"},
        "NOLAND": {"accepted": True, "reason": "verified", "landed": False, "pr": "(push failed rc=1)",
                   "receipt": {"h": "dry-noland"}, "patch": "diff --git a/src.py b/src.py\n+x"},
        "INTEGRITY": {"accepted": False, "reason": "integrity_violation", "patch": "",
                      "integrity": {"hard": [{"file": "test_x.py"}]}, "receipt": {"h": "dry-integ"}},
    }

    def dry_runner(repo, prompt, test_cmd, **kw):
        for key, result in table.items():
            if key in (prompt or ""):
                return dict(result)
        if "BOOM" in (prompt or ""):
            raise RuntimeError("dry runner: scripted failure")
        return {"accepted": False, "reason": "tests", "patch": "", "receipt": {"h": "dry-fail"}}

    return dry_runner


# --------------------------------------------------------------------------- cli / smoke
def main(argv=None):
    ap = argparse.ArgumentParser(description="SEIF controller: drive a backlog through the gate via the "
                                             "two-plane runtime (persistent controller + lean workers).")
    ap.add_argument("--backlog", help="path to a JSON list of task dicts")
    ap.add_argument("--route-dir", default=None, help="route table dir (default 01_routes/)")
    ap.add_argument("--max-tasks", type=int, default=5)
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--min-accept-rate", type=float, default=0.0)
    ap.add_argument("--no-pr", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="use the injectable fake worker (no model/network)")
    a = ap.parse_args(argv)
    backlog = json.load(open(a.backlog)) if a.backlog else []
    cfg = SL.LoopConfig(max_tasks=a.max_tasks, budget_per_task=a.budget, timeout=a.timeout,
                        make_pr=not a.no_pr, min_accept_rate=a.min_accept_rate)
    ctrl = Controller(backlog, route_dir=a.route_dir, cfg=cfg, dry_run=a.dry_run)
    out = ctrl.run()
    print(json.dumps({k: v for k, v in out.items() if k != "records"}, indent=2))
    return 0


def _smoke():
    """No-model smoke test of the whole control plane: load the real route table, dispatch a scripted
    dry-run backlog, assert caps + accept-rate floor + the founder queue all fire. Run: `controller.py --smoke`."""
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="seif-ctrl-smoke-")
    try:
        from tripartite import EpisodicMemory, WorkingMemory
        mem = Memory()
        mem.episodic = EpisodicMemory(path=os.path.join(tmp, "ep.jsonl"))
        mem.working = WorkingMemory(path=os.path.join(tmp, "w.json"))
        qpath = os.path.join(tmp, "queue.jsonl")

        def task(tid, kind, **kw):
            return {"task_id": tid, "repo": tmp, "task": kind, "test_cmd": "x", **kw}

        # 1) the real route table loads (at least the shipped seif-source-fix route)
        routes, warns = load_route_table()
        assert any(r.get("id") == "seif-source-fix" for r in routes), (routes, warns)

        # 2) one ACCEPT lands → queued for the founder; mixed backlog respects caps
        cfg = SL.LoopConfig(max_tasks=10)
        ctrl = Controller([task("ok", "ACCEPT", lesson="resolve paths"),
                           task("noland", "NOLAND"),
                           task("bad", "INTEGRITY"),
                           task("fail", "anything")],
                          mem=mem, cfg=cfg, dry_run=True, queue_path=qpath)
        out = ctrl.run()
        assert out["attempted"] == 4 and out["accepted"] == 2, out  # ACCEPT + NOLAND both pass tests
        assert out["landed"] == 1, out                              # only ACCEPT actually landed
        queued = ctrl.founder_queue()
        assert len(queued) == 1 and queued[0]["task_id"] == "ok", queued
        assert out["dry_run"] is True and out["route_table"]["loaded"] >= 1, out

        # 3) the accept-rate floor bails early (REUSED from run_loop)
        fail_backlog = [task(f"f{i}", "fail") for i in range(8)]
        cfg2 = SL.LoopConfig(max_tasks=8, min_accept_rate=0.5, floor_after=3)
        out2 = Controller(fail_backlog, mem=mem, cfg=cfg2, dry_run=True,
                          queue_path=os.path.join(tmp, "q2.jsonl")).run()
        assert out2["attempted"] == 3 and "accept_rate_floor" in out2["stopped_reason"], out2

        # 4) the max_tasks cap truncates
        out3 = Controller(fail_backlog, mem=mem, cfg=SL.LoopConfig(max_tasks=2), dry_run=True,
                          queue_path=os.path.join(tmp, "q3.jsonl")).run()
        assert out3["attempted"] == 2 and out3["skipped"] == 6, out3

        print("controller smoke PASS")
        print("  route-table loads · accept→queued · noland/integrity→not-queued · floor→early-stop · cap→truncate")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        _smoke()
    else:
        sys.exit(main())
