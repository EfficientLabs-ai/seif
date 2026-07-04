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
import integrity_guard as IG  # noqa: E402
import checkpoint as CP       # noqa: E402  (L4: register verified states / record failure forensics)
import pr_format as PF        # noqa: E402  (professional, consistent PR body + commit formatting)
import usage_meter as UM      # noqa: E402  (token + cost accounting — make every model call measurable)
import ecp_route as ECP       # noqa: E402  (ECP route compiler — opt-in per-task minimum environment)

CLAUDE = "/home/neo/.local/bin/claude"

# OPT-IN exact-fingerprint result cache (logos/result_cache.py). OFF by default; enabled per-call via the
# `result_cache=` param or the SEIF_RESULT_CACHE env var (truthy). A HIT reuses a prior accepted patch +
# receipt and SKIPS the model call entirely. The cache is imported lazily so the default path never touches
# it (and never requires the L1 backend). EXACT-only: any field mismatch is a MISS (no fuzzy reuse).
def _result_cache_enabled(flag):
    if flag is not None:
        return bool(flag)
    return os.environ.get("SEIF_RESULT_CACHE", "").strip().lower() in ("1", "true", "yes", "on")


def _resolve_commit(repo, ref):
    """Resolve a git ref to a full commit SHA (the cache pins the EXACT base contents, not a moving ref
    like 'HEAD'). Returns the resolved SHA, or the original ref if resolution fails (degrade, never crash)."""
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", ref],
                             capture_output=True, text=True).stdout.strip()
        return out or ref
    except Exception:  # noqa: BLE001
        return ref


# ECP route manifests live alongside the SEIF source (sibling of logos/), NOT in the target repo: these are
# SEIF's own per-task policies. Auto-select loads every *.yaml here and asks match_route for the best fit.
ROUTES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "01_routes")


def _load_routes(routes_dir=ROUTES_DIR):
    """Load + structurally-validate every route manifest in `routes_dir`. Best-effort and no-throw: a
    missing dir, unreadable file, or invalid manifest is skipped (auto-select must never break the gate —
    a bad route file degrades to 'no route matched', i.e. current behavior). Returns a list of route dicts."""
    routes = []
    try:
        names = sorted(os.listdir(routes_dir))
    except OSError:
        return routes
    for name in names:
        if not (name.endswith(".yaml") or name.endswith(".yml")):
            continue
        try:
            r = ECP.load_route(os.path.join(routes_dir, name))
            if isinstance(r, dict) and not ECP.validate_route(r):   # only well-formed routes are eligible
                routes.append(r)
        except Exception:  # noqa: BLE001 — a broken/unloadable manifest is skipped, never fatal
            continue
    return routes

# Protected surface for PROJECT-mode reward-hacking defense: a candidate must never make tests "pass"
# by editing the tests, the CI, or the test runner itself. Source-only fixes. (Callers can override for
# a task that legitimately adds tests — but the autonomous default protects the grader.)
PROTECTED = (
    "test/", "tests/", "spec/", "specs/", "__tests__/", "e2e/",
    "test_*.py", "*_test.py", "*.test.js", "*.test.ts", "*.test.tsx", "*.test.jsx",
    "*.test.mjs", "*.spec.js", "*.spec.ts", "*.spec.tsx", "*.spec.py", "conftest.py",
    ".github/", "jest.config.*", "vitest.config.*", "pytest.ini", "tox.ini", "playwright.config.*",
    "run-tests.*", "run_tests.*",
)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "task"


# A failing test prints file paths in a handful of shapes; pull the source files it actually named so we
# can scope the retry context to the real blast radius. Conservative on purpose — only paths that LOOK
# like project source (have a code extension) are treated as seeds; noise becomes "no packet", never a crash.
_SRC_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".go", ".rs", ".java", ".rb", ".c", ".cc",
            ".cpp", ".h", ".hpp", ".cs", ".php", ".swift", ".kt", ".scala")
# `File "x/y.py", line N` (Python tracebacks) · `at x/y.ts:12:3` (node) · bare `pkg/mod.py:42` (pytest/grep).
_FILE_PATTERNS = (
    re.compile(r'File "([^"]+)"'),
    re.compile(r'\bat\s+([^\s():]+\.[A-Za-z]+):\d+'),
    re.compile(r'([A-Za-z0-9_./\-]+\.[A-Za-z]+):\d+'),
)


# A path is allowed into the packet only if it matches a strict file-path shape (no spaces, no newlines, no
# shell/prompt-control punctuation). The packet text is built from two UNTRUSTED sources — failing-test
# output AND graph `source_file` strings (graphify-out/graph.json can carry arbitrary text) — so every path,
# whatever its origin, passes this whitelist before it is formatted into the prompt. Anything that doesn't
# look like a plain relative path is dropped rather than escaped, so a tampered graph can't smuggle directives.
_SAFE_PATH = re.compile(r"[A-Za-z0-9_./\-]{1,200}\Z")


def _safe_paths(paths):
    """Keep only whitelist-clean relative paths, de-duped in first-seen order (defense for graph-derived
    strings injected into the retry prompt)."""
    seen, out = set(), []
    for p in (paths or []):
        p = (str(p) if p is not None else "").strip()
        if p and _SAFE_PATH.match(p) and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _referenced_files(feedback):
    """Source files named in failing-test output, de-duped in first-seen order. Pure + total: any input
    (incl. None / garbage) yields a list, never an exception — so the retry packet is always safe to build."""
    seen, out = set(), []
    text = feedback or ""
    for pat in _FILE_PATTERNS:
        for m in pat.findall(text):
            path = (m or "").strip().lstrip("./")
            if not path or not path.lower().endswith(_SRC_EXT):
                continue
            if not _SAFE_PATH.match(path):       # reject anything that isn't a plain relative path
                continue
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _retry_context_packet(repo, feedback):
    """Graph-scoped retry context for attempt N+1: the blast-radius NEIGHBORS of the files the failing
    tests named — what DEPENDS ON them (L3 reverse closure via delta_plan._blast_radius) and what they
    DEPEND ON (forward closure via SemanticMemory.dependencies). Returns a short text block, or "" when
    there is nothing to add. REGRESSION-SAFETY context, not a token saver (graph scoping measured ~0% on
    tokens). Degrades cleanly: absent graphify-out / store / module ⇒ "" with no error, never a crash."""
    try:
        seeds = _referenced_files(feedback)
        if not seeds:
            return ""
        import delta_plan as DP  # noqa: E402  (logos/ already on sys.path)
        # reverse closure (what changing these touches) — None means "no graph to answer from".
        impacted = DP._blast_radius(repo, seeds)
        # forward closure (what these depend on) — via the same L3 view delta_plan composes over.
        depends_on = None
        try:
            from tripartite import SemanticMemory  # noqa: E402  (memory/ on sys.path via delta_plan import)
            sm = SemanticMemory(repo)
            if sm.available:
                deps = set()
                for s in seeds:
                    deps.update(sm.dependencies(s))
                depends_on = sorted(deps) if sm.available else None
        except Exception:  # noqa: BLE001 — forward closure is advisory; absence ⇒ omit, never crash
            depends_on = None
        # Sanitize every graph-derived path before it reaches the prompt: graph `source_file` strings are an
        # UNTRUSTED source, so whitelist-filter them (a tampered graph can't smuggle prompt directives).
        impacted = _safe_paths(impacted)
        depends_on = _safe_paths(depends_on)
        # If the graph could answer NEITHER direction, there is no graph-scoped value to add → no packet.
        if not impacted and not depends_on:
            return ""
        lines = ["GRAPH-SCOPED CONTEXT (blast radius of the files the failing tests named — reference data,",
                 "regression-safety only): when you fix the source, check you do not break these neighbors.",
                 f"  failing-test files: {', '.join(seeds[:12])}"]
        if impacted:
            lines.append(f"  depend on the above (could regress): {', '.join(impacted[:20])}")
        if depends_on:
            lines.append(f"  the above depend on: {', '.join(depends_on[:20])}")
        return "\n".join(lines)
    except Exception:  # noqa: BLE001 — context is advisory; ANY failure ⇒ no packet, never break the gate
        return ""


def _claude_edit(worktree, task, feedback, first, timeout, model=None, extra_flags=None):
    """Run the editor sub-agent once (with bounded empty-envelope retries).

    Returns (rc, usage). usage carries an extra metering key, `empty_retries` = how many zero-token
    envelopes were observed and retried past before this (accepted/final) call. A non-zero count is an
    INFRA-hiccup fingerprint the receipt records, so a 'no_change'/timeout is not silently confused with a
    flaky empty response. The 2-tuple contract is unchanged — empty_retries rides on the usage dict."""
    if first:
        prompt = (f"You are making a focused change in this repository (cwd).\n\nTASK:\n{task}\n\n"
                  "Edit the SOURCE to accomplish it and make the project's tests pass. Do NOT edit tests. "
                  "Make the change and stop.")
    else:
        # `feedback` is already bounded by the caller (seif_run truncates test output and appends an
        # optional graph-scoped packet), so embed it whole here rather than re-truncating it.
        prompt = (f"You are fixing a change in this repository (cwd).\n\nTASK:\n{task}\n\n"
                  f"The project's tests are STILL FAILING:\n{feedback}\n\n"
                  "Fix the SOURCE so the tests pass. Do NOT edit tests. Make the change and stop.")
    # --output-format json makes the call cost-attributable: the result envelope carries usage + cost.
    # acceptEdits still applies (edits happen); only the FINAL print is a JSON envelope we meter.
    # --model pins the model when the caller requests one (so a measured/routed model is honoured).
    # extra_flags = an ECP route's lean flags (--strict-mcp-config / --setting-sources project / tool
    # allow-deny) compiled by ecp_route — the per-task "minimum operating environment".
    argv = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "acceptEdits"]
    if model:
        argv += ["--model", model]
    if extra_flags:
        argv += list(extra_flags)
    argv.append(prompt)
    # Retry-on-empty: an empty (zero-token) envelope is an INFRA hiccup, not "the agent made no change".
    # A genuine no-change still returns non-zero usage (the prompt was processed). Retrying a real no-change
    # is harmless (still no diff); NOT retrying an empty envelope wastes a whole budget step. Bounded to 3.
    def _tag(rc, usage, retries):
        usage["empty_retries"] = retries          # metering: zero-token retries observed for this call
        return rc, usage
    last_usage = UM.parse_usage("")
    empty_retries = 0
    for _ in range(3):
        try:
            p = subprocess.run(argv, cwd=worktree, timeout=timeout, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            return _tag(None, UM.parse_usage(""), empty_retries)
        usage = UM.parse_usage(p.stdout)
        last_usage = usage
        if UM.total_tokens(usage) > 0:
            return _tag(p.returncode, usage, empty_retries)        # accepted call; retries seen so far
        empty_retries += 1          # this call returned zero tokens — the next loop iteration is a retry
        last_rc = p.returncode
    # all bounded attempts were empty: report retries = attempts-after-the-first (i.e. empty_retries - 1).
    return _tag(last_rc, last_usage, max(empty_retries - 1, 0))


def _has_remote(repo):
    r = subprocess.run(["git", "-C", repo, "remote"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _repo_slug(repo):
    """OWNER/REPO from the origin remote URL (gh -R wants this, not a local path)."""
    url = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def _resolve_base(repo, base):
    """Resolve the clean-room base ref. 'last-healthy' → the last HEALTHY L4 checkpoint's commit (or
    'HEAD' if none yet); any other value (incl. the default 'HEAD') is returned unchanged. Defensive: a
    missing/None/malformed checkpoint record falls back to 'HEAD' and never crashes the run."""
    if base != "last-healthy":
        return base
    try:
        last = CP.last_healthy(repo)
        commit = last.get("commit") if isinstance(last, dict) else None
    except Exception:  # noqa: BLE001 — base resolution must never break the gate; degrade to HEAD
        commit = None
    return commit or "HEAD"


def _pr_base_branch(repo, base_ref):
    """The remote branch the run was actually cut from, or None for the default flow.

    A run cut from a feature branch must open a STACKED PR against that branch: `gh pr create`
    without --base targets the default branch, which makes the PR show the whole parent diff,
    misstates its scope, and inherits every parent conflict (this is how efficientlabs-web#35
    became a 33-file "one new file" PR). Returns None when the base is the default branch,
    detached, unknown, or not on the remote — the caller then omits --base."""
    try:
        name = base_ref
        if name in ("HEAD", None, ""):
            name = subprocess.run(["git", "-C", repo, "symbolic-ref", "--short", "-q", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
        if not name:
            return None
        # normalize remote-tracking / fully-qualified spellings ('origin/feat/x',
        # 'refs/heads/feat/x') to the plain branch name — otherwise the remote probe
        # below looks up refs/remotes/origin/origin/... and silently falls back to
        # the default branch, recreating the over-broad PR this helper prevents
        for prefix in ("refs/remotes/origin/", "refs/heads/", "origin/"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        if not name:
            return None
        # stacking is only meaningful when the branch exists on the remote
        on_remote = subprocess.run(["git", "-C", repo, "show-ref", "--verify", "-q",
                                    f"refs/remotes/origin/{name}"], capture_output=True)
        if on_remote.returncode != 0:
            return None
        d = subprocess.run(["git", "-C", repo, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD"],
                           capture_output=True, text=True).stdout.strip()
        default = d.split("/", 1)[-1] if d else "main"
        if name == default:
            return None
        # if the local base has commits the remote branch doesn't, the child PR will
        # carry them against the stale remote base — still strictly narrower than
        # basing on the default branch, so stack anyway but say so out loud
        local = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", name],
                               capture_output=True, text=True).stdout.strip()
        if local:
            contained = subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor",
                                        local, f"refs/remotes/origin/{name}"], capture_output=True)
            if contained.returncode != 0:
                sys.stderr.write(f"[/seif] stacked base '{name}' has unpushed commits — the PR diff "
                                 f"will include them until the parent branch is pushed\n")
        return name
    except Exception:  # noqa: BLE001 — PR base resolution must never break PR submission
        return None


def _pr_title_subject(task):
    """First line of the task, truncated at a WORD boundary — a readable PR title, never raw
    goal text sheared mid-word (the old task[:64] produced titles like '…(create t')."""
    line = _inline_first_line(task)
    if len(line) <= 64:
        return line
    cut = line[:64].rsplit(" ", 1)[0].rstrip(" ,;:.-(") or line[:64]
    return cut + "…"


def _inline_first_line(text):
    return (str(text or "").strip().splitlines() or [""])[0].strip()


def seif_run(repo, task, test_cmd, budget=3, base="HEAD", timeout=600, make_pr=True, protected=PROTECTED,
             model=None, route=None, result_cache=None):
    repo = os.path.abspath(repo)
    base = _resolve_base(repo, base)
    # ECP route selection. Three modes, in order of precedence:
    #   kill-switch   route=False, or env SEIF_NO_ROUTE=1  -> no route (route_id_selected='none').
    #   explicit      route=<dict|path>                    -> compile + apply exactly that route (opt-in).
    #   AUTO (default) route=None                          -> load 01_routes/*.yaml, match_route(intent=task);
    #                                                         on a hit compile + apply; on a miss, current behavior.
    # When a route is applied it sets: lean flags (the per-task minimum operating environment), the routed
    # model (an explicit `model` arg still wins), and the turn budget — identical for explicit + auto routes,
    # so compile_route's measured constraint (cheap default -> full lean; pinned strong -> mcp-only + warning)
    # is honored either way.
    lean_flags = None
    route_id_selected = "none"
    # Graph-scoped retry context (regression-safety, NOT a token saver — graph scoping measured ~0% on
    # tokens). DEFAULT ON; when a route IS active it is gated behind the route's memory policy (set below).
    graph_scope = True
    disabled = (route is False) or (os.environ.get("SEIF_NO_ROUTE") == "1")
    route_to_compile = None
    if disabled:
        print("[/seif] ECP route selection DISABLED (kill-switch: route=False or SEIF_NO_ROUTE=1)")
    elif route is not None:
        # explicit route: a pre-compiled dict, a manifest dict, or a manifest path.
        route_to_compile = route
    else:
        # AUTO-select (the default): pick the best-fit manifest for this task's intent.
        routes = _load_routes()
        match = ECP.match_route(routes, intent=task)
        if match:
            route_to_compile = match
            print(f"[/seif] ECP auto-select MATCHED route={match.get('id')} for intent")
        else:
            print("[/seif] ECP auto-select: no route matched — default (full) behavior")
    if route_to_compile is not None:
        # at task start nothing has changed yet, so the graph-selector context is empty; the route's
        # `required` context + the lean flags + routed model are what apply here (graph-scoped context on
        # retries is a follow-up). Accept a pre-compiled dict or a manifest dict/path.
        compiled = (route_to_compile
                    if isinstance(route_to_compile, dict) and "lean_flags" in route_to_compile
                    else ECP.compile_route(
                        route_to_compile if isinstance(route_to_compile, dict)
                        else ECP.load_route(route_to_compile), changed_files=None))
        lean_flags = compiled.get("lean_flags")
        route_id_selected = compiled.get("route_id") or "none"
        model = model or compiled.get("model")          # explicit model arg still wins
        rb = (compiled.get("budget") or {}).get("max_turns")
        if rb:
            budget = rb
        # Gate graph-scoped retry context behind the route's memory policy: a route that does NOT declare a
        # graph memory backend (or sets it falsy/disabled) opts OUT of the L3 packet. memory.graph present
        # and not explicitly disabled ⇒ keep it on.
        mem_pol = compiled.get("memory") if isinstance(compiled.get("memory"), dict) else {}
        graph_pol = mem_pol.get("graph")
        graph_scope = bool(graph_pol) and not (isinstance(graph_pol, dict) and graph_pol.get("enabled") is False)
        print(f"[/seif] ECP route={compiled.get('route_id')} lean={compiled.get('lean')} model={model} "
              f"graph_scope={graph_scope} flags={' '.join(lean_flags or [])}")
        for w in compiled.get("warnings") or []:
            print(f"[/seif] ECP ⚠️ {w}")
    # OPT-IN result cache (off by default). The fingerprint pins the EXACT inputs that determine the
    # model's output: task, the RESOLVED base commit (not a moving ref), test_cmd, the sorted content
    # hashes of the changed files (empty at task start — base_commit already pins the starting tree),
    # the model, and the lean flags. A hit lets us reuse a prior accepted patch + receipt and SKIP the
    # model entirely. Built lazily so the default path never imports the cache or its L1 backend.
    rcache, cache_fp = None, None
    if _result_cache_enabled(result_cache):
        try:
            import result_cache as RC  # noqa: E402
            rcache = result_cache if isinstance(result_cache, RC.ResultCache) else RC.ResultCache()
            base_commit = _resolve_commit(repo, base)
            # No files have changed yet at the cache-check point; the base commit pins the starting tree,
            # so the changed-file set is empty here by construction (exact + conservative).
            changed_hashes = RC.changed_file_hashes(repo, [])
            cache_fp = (task, base_commit, test_cmd, changed_hashes, model, lean_flags)
            # `protected` is passed as a separate keyword, not folded into cache_fp (Codex P2, closed):
            # a patch accepted under a RELAXED --protected override must never be replayed for an
            # identical task/base/test/model/flags run under the STRICT default set — the cache-hit path
            # below never re-runs IG.is_clean, so the protected set MUST be part of the key.
            hit = rcache.lookup(*cache_fp, protected=protected)
            if hit is not None:
                print(f"[/seif] RESULT-CACHE HIT (backend={rcache.backend}) — reusing prior accepted patch "
                      f"+ receipt; SKIP model call. receipt h={(hit.get('receipt') or {}).get('h')}")
                # `checkpoint` stays None on a cache hit (no NEW checkpoint is minted here) so the return
                # shape is consistent with the verified path's dict-or-None contract — never a bare string.
                # The prior run's checkpoint id is surfaced separately as `checkpoint_id` for provenance.
                return {"accepted": True, "landed": False, "branch": hit.get("branch"),
                        "pr": None, "worktree": None, "receipt": hit.get("receipt"),
                        "patch": hit.get("patch"), "reason": "cache_hit", "integrity": None,
                        "checkpoint": None, "checkpoint_id": hit.get("checkpoint_id"),
                        "usage": UM.empty(), "model_requested": model, "model_actual": None,
                        "cache_hit": True}
            print(f"[/seif] result-cache MISS (backend={rcache.backend}) — running model")
        except Exception as e:  # noqa: BLE001 — a cache hiccup must NEVER block the gate; degrade to no-cache
            sys.stderr.write(f"[/seif] result-cache disabled (error: {e!r})\n")
            rcache, cache_fp = None, None
    spend = UM.empty()   # token + cost accounting, summed across every attempt of this task — initialized
    # BEFORE the clean room so a checkpoint failure below can still mint a (empty-spend) receipt.
    try:
        wt = H.checkpoint(repo, base)
    except BaseException as e:  # noqa: BLE001 — clean-room creation itself failed (tmpfs exhaustion, bad
        # base ref, git failure) OR an operator abort (KeyboardInterrupt/SystemExit) landed during it —
        # catching only Exception here left THIS exact scenario un-receipted, the one the PR title claims
        # to close (Codex, closed). No worktree exists yet, so there's nothing to discard, but the
        # disposition must still be receipted — this was the last un-receipted terminal path in the gate.
        final_outcome = "ERROR" if isinstance(e, Exception) else "ABORT"
        try:
            H._receipt(repo, task, test_cmd, {"outcome": "error", "exit_code": None}, "", usage=spend,
                       metering={"attempt_number": 0, "empty_response_retries": 0, "checkpoint_id": None,
                                 "route_id_selected": route_id_selected,
                                 "evidence_result": f"clean-room checkpoint failed: {type(e).__name__}: {str(e)[:200]}",
                                 "final_outcome": final_outcome})
        except Exception:  # noqa: BLE001 — receipt bookkeeping must never mask the original fault
            pass
        raise
    feedback, passed, result, patch, integrity = "", False, None, "", None
    # production metering (A-loop): attempt_number = the budget step that produced the accepted (or last)
    # patch; empty_response_retries = total zero-token retries absorbed across all steps (an infra-hiccup
    # fingerprint, summed because each step's _claude_edit reports its own retries on the usage dict).
    attempt_number, empty_response_retries = 0, 0
    print(f"[/seif] repo={os.path.basename(repo)} test='{test_cmd}' budget={budget}\n[/seif] clean room: {wt}")
    try:
        def _stage_diff():
            subprocess.run(["git", "-C", wt, "add", "-A"], capture_output=True)
            return subprocess.run(["git", "-C", wt, "diff", "--cached"], capture_output=True, text=True).stdout

        for step in range(1, budget + 1):
            integrity = None                          # never carry a prior step's verdict forward
            attempt_number = step                     # track the budget step we are on (accepted patch's step)
            rc, usage = _claude_edit(wt, task, feedback, step == 1, timeout, model=model, extra_flags=lean_flags)
            empty_response_retries += int(usage.get("empty_retries", 0) or 0)  # zero-token retries this step
            UM.accumulate(spend, usage)               # meter every model call, pass or fail
            patch = _stage_diff()
            if not patch.strip():
                print(f"[/seif] step {step}: agent made no change (rc={rc}) — stop")
                result = {"outcome": "no_change", "exit_code": None}
                break
            result = H.run_tests(wt, test_cmd, timeout=timeout)
            print(f"[/seif] step {step}: tests -> {result['outcome']} (exit {result['exit_code']}, {result['seconds']}s)")
            if result["outcome"] == "pass":
                # Re-snapshot AFTER tests: running the suite can touch tracked files, and we must
                # integrity-check (and later commit) EXACTLY what is graded — not the pre-test snapshot.
                patch = _stage_diff()
                clean, integrity = IG.is_clean(patch, protected)
                if clean:
                    passed = True
                    break
                # Tests pass BUT the candidate edited a protected surface (tests/CI/runner) = reward-hacking.
                # Reject this candidate; feed the violation back and let the remaining budget try a clean fix.
                violated = [h["file"] for h in integrity["hard"]]
                result["outcome"] = "integrity_violation"
                print(f"[/seif] step {step}: INTEGRITY VIOLATION — protected edits: {violated}")
                feedback = ("Tests passed BUT your change edited a PROTECTED path (tests, CI, or the test "
                            f"runner): {violated}. That is not allowed — fix the SOURCE only, never the "
                            "tests or test config. Make the source change that passes the EXISTING tests.")
                continue
            feedback = (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-4500:]
            # Graph-scoped retry context: append the blast-radius neighbors of the files THESE tests named
            # so the next attempt sees its regression surface. Gated by the route's memory policy (default
            # ON without a route); degrades to "" — no packet, no crash — when the graph/store is absent.
            if graph_scope:
                packet = _retry_context_packet(repo, feedback)
                if packet:
                    feedback = feedback + "\n\n" + packet
        print(f"[/seif] spend: {UM.summary_line(spend)}")
        # CBOM guard (item 3): the receipt's usage already records the model actually served (model_actual).
        # If the caller pinned a model and a DIFFERENT one was served (e.g. a setting-strip forced a
        # downgrade), warn loudly — a silent model swap must never be mistaken for an optimization.
        model_actual = spend.get("model")
        if model and model_actual and model_actual.split("[")[0] != model:
            print(f"[/seif] ⚠️ MODEL MISMATCH: requested {model}, served {model_actual}")
        # production metering shared by both paths. evidence_result is a short, human-scannable verdict:
        # tests outcome + the integrity/protected-path status the gate actually observed.
        def _evidence_result(_result, _integrity, _passed):
            outcome = (_result or {}).get("outcome", "no_change")
            if _passed:
                return f"tests pass (exit 0); integrity clean; protected paths untouched"
            if outcome == "integrity_violation":
                viol = [h.get("file") for h in (_integrity or {}).get("hard", [])]
                return f"tests pass BUT integrity FAIL; protected paths edited: {viol}"
            if outcome == "no_change":
                return "no patch produced (agent made no change)"
            ec = (_result or {}).get("exit_code")
            return f"tests {outcome} (exit {ec}); integrity n/a"
        if not passed:
            # final disposition: an integrity violation / failing tests with budget remaining is a REJECT;
            # a clean fail that consumed the whole budget is BUDGET_EXHAUSTED (a distinct, actionable class).
            why = {"integrity_violation": "integrity_violation",
                   "no_change": "no_change"}.get((result or {}).get("outcome"), "tests")
            final_outcome = ("BUDGET_EXHAUSTED" if why == "tests" and attempt_number >= budget else "REJECTED")
            metering = {"attempt_number": attempt_number, "empty_response_retries": empty_response_retries,
                        "checkpoint_id": None, "route_id_selected": route_id_selected,
                        "evidence_result": _evidence_result(result, integrity, False),
                        "final_outcome": final_outcome}
            rec = H._receipt(repo, task, test_cmd, result or {"outcome": "no_change", "exit_code": None},
                             patch, usage=spend, metering=metering)
            H.discard(repo, wt)                                   # ATMS rollback — main untouched
            # ASRS forensics: record what broke + the rollback target (last healthy checkpoint), so the
            # loop can avoid repeating the failure class. Best-effort — never alters the gate's verdict.
            try:
                CP.record_failure(repo, broken_patch_sha=H._sha(patch), failure_reason=why,
                                  affected_modules=IG.changed_files(patch or ""), triggered_by=task[:200])
            except Exception:  # noqa: BLE001
                pass
            print(f"[/seif] NOT VERIFIED ({why}/{final_outcome}) — rolled back. receipt h={rec.get('h')}")
            return {"accepted": False, "receipt": rec, "patch": patch, "reason": why,
                    "integrity": integrity, "usage": spend, "route_id_selected": route_id_selected,
                    "model_requested": model, "model_actual": spend.get("model")}
        # success: land on a branch (never main), PR if a remote exists
        branch = f"seif/{_slug(task)}-{time.strftime('%m%d-%H%M%S', time.gmtime())}-{os.urandom(2).hex()}"
        # commit the EXACT integrity-checked index (-m, not -am) so the PR contents == what was graded.
        # conventional-commits message via the house-style builder — same shape as the PR + manual commits.
        # (The receipt is minted AFTER the checkpoint below so its hash can cover checkpoint_id; the commit
        # message references the patch sha, not the receipt hash, to keep that ordering one-directional.)
        commit_msg = PF.build_commit(
            "feat", task[:72], scope="seif",
            bullets=[f"tests pass (exit 0); SEIF patch {H._sha(patch)}"],
            trailers=["Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"])
        for c in (["git", "-C", wt, "checkout", "-q", "-b", branch],
                  ["git", "-C", wt, "-c", "user.name=Neo The Architect",
                   "-c", "user.email=founder@efficientlabs.ai", "commit", "-q", "-m", commit_msg]):
            subprocess.run(c, check=True, capture_output=True)
        # L4: register this VERIFIED state as a healthy checkpoint (commit + proof + context signature),
        # chained to the prior healthy one — turns the gate's success into a promotable known-good state.
        # Best-effort: checkpoint bookkeeping must never break a verified landing.
        checkpoint = None
        try:
            commit = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"],
                                    capture_output=True, text=True).stdout.strip()
            # proof.receipt is CP's required verified-state evidence hash; we use the graded patch sha (a
            # stable, non-empty hash of EXACTLY what was tested) so the checkpoint can be minted BEFORE the
            # receipt — letting the receipt's hash then cover this checkpoint's id (one-directional link).
            checkpoint = CP.create(
                repo, task[:80], commit=commit,
                proof={"outcome": "pass", "receipt": H._sha(patch), "test_cmd": test_cmd,
                       "exit_code": (result or {}).get("exit_code")},
                context={"task": task, "files_changed": IG.changed_files(patch or "")},
                parent=(CP.last_healthy(repo) or {}).get("id"))
        except Exception:  # noqa: BLE001
            checkpoint = None
        # mint the receipt now that the healthy checkpoint exists, so checkpoint_id is hash-covered.
        # final_outcome=ACCEPTED_PR: the gate accepted + committed + checkpointed; the PR submission below
        # is best-effort and does not change the accepted disposition (landed is reported separately).
        metering = {"attempt_number": attempt_number, "empty_response_retries": empty_response_retries,
                    "checkpoint_id": (checkpoint or {}).get("id"), "route_id_selected": route_id_selected,
                    "evidence_result": _evidence_result(result, integrity, True),
                    "final_outcome": "ACCEPTED_PR"}
        rec = H._receipt(repo, task, test_cmd, result or {"outcome": "no_change", "exit_code": None},
                         patch, usage=spend, metering=metering)
        # EVERYTHING FROM HERE THROUGH PR SUBMISSION IS BEST-EFFORT AND ISOLATED (Codex P1, closed —
        # WIDENED after round-2 review found the fix only covered the push/gh-create block specifically,
        # leaving the result-cache store and the _has_remote() call in this SAME post-ACCEPTED_PR-receipt
        # region with the identical unguarded-escape exposure): the work is already verified + committed +
        # receipted + checkpointed above, so NOTHING in this region — the cache write, the remote check,
        # the push, the PR create, or a future addition to this block — may reach the outer
        # discard-and-double-receipt handler. One outer BaseException catch covers the whole region rather
        # than patching individual call sites, so this class of bug can't resurface as the block grows.
        pr_url, landed = None, False
        has_remote = False  # safe default if the try below raises before this is ever assigned
        try:
            # OPT-IN result cache: store this VERIFIED result under its exact fingerprint so an IDENTICAL
            # re-run (same task/base/test/files/model/flags) reuses this patch + receipt and skips the
            # model. Its own narrower `except Exception` preserves the existing "log and continue" shape
            # for the common case; the outer BaseException catch below is the safety net underneath it.
            if rcache is not None and cache_fp is not None:
                try:
                    rcache.store(*cache_fp, protected=protected, patch=patch, receipt=rec,
                                 extra={"branch": branch, "checkpoint_id": (checkpoint or {}).get("id")})
                except Exception as e:  # noqa: BLE001
                    sys.stderr.write(f"[/seif] result-cache store skipped (error: {e!r})\n")
            # _has_remote(repo) is called ONCE and cached (Codex, round 3, closed): a second call further
            # below, purely to compute the human-readable `where` string, used to sit OUTSIDE this try
            # block entirely — an interrupt landing in THAT unguarded call still reached the outer
            # discard-and-double-receipt handler even after round 2 widened everything else. Eliminating
            # the second call (rather than wrapping it in yet another handler) removes the exposure
            # entirely instead of relying on catching up with every call site individually.
            has_remote = _has_remote(repo)
            # honest landing state: 'accepted' = tests passed (true regardless); 'landed' = push+PR actually succeeded.
            if make_pr and has_remote:
                push = subprocess.run(["git", "-C", wt, "push", "-q", "-u", "origin", branch], capture_output=True, text=True)
                if push.returncode != 0:
                    pr_url = f"(push failed rc={push.returncode}: {push.stderr[-160:]})"
                else:
                    slug = _repo_slug(repo)
                    # professional, scannable PR body in the SEIF house style (pr_format) — same shape every PR.
                    changed = IG.changed_files(patch or "")
                    title = PF.build_commit("feat", _pr_title_subject(task), scope="seif").splitlines()[0]
                    body = PF.build_pr_body(
                        summary=task[:200],
                        problem=task[:500],
                        impact=f"{len(changed)} file(s) changed behind the SEIF gate; tests, integrity "
                               f"guard, receipt, and checkpoint below all ran for real.",
                        changes=[(f, "—") for f in changed],
                        verification=[(f"Tests (`{test_cmd}`)", f"pass (exit {(result or {}).get('exit_code')})", True),
                                      ("Integrity guard", "clean (no protected/test/CI edits, no bypass sentinel)", True),
                                      ("SEIF receipt", f"`{rec.get('h')}`", True),
                                      ("L4 checkpoint", f"`{(checkpoint or {}).get('id')}`", bool(checkpoint))],
                        evidence=((result or {}).get("stdout", "") or "")[-1500:],
                        issue=PF.issue_ref(task))
                    # A run cut from a feature branch opens a STACKED PR against that branch —
                    # basing it on the default branch misstates scope and inherits parent conflicts.
                    pr_base = _pr_base_branch(repo, base)
                    cmd = ["gh", "pr", "create", "-R", slug or repo, "--head", branch,
                           "--title", title, "--body", body]
                    if pr_base:
                        cmd += ["--base", pr_base]
                    pr = subprocess.run(cmd, cwd=wt, capture_output=True, text=True)
                    if pr.returncode == 0:
                        pr_url, landed = pr.stdout.strip(), True
                    else:
                        pr_url = f"(branch pushed; pr create rc={pr.returncode}: {pr.stderr[-160:]})"
        except BaseException as e:  # noqa: BLE001 — see the region comment above: nothing here may reach
            # the outer discard-and-double-receipt handler, whether it's a push/gh hiccup, an operator
            # abort, or a failure in the cache-store/has_remote steps this catch now also covers.
            pr_url = f"(post-accept step failed or interrupted, branch and receipt are safe: {e!r})"
        where = pr_url or ("local branch only (no remote)" if not make_pr or not has_remote else None)
        cp_id = (checkpoint or {}).get("id")
        print(f"[/seif] VERIFIED ✓  branch={branch}  landed={landed}  where={where}  "
              f"receipt h={rec.get('h')}  checkpoint={cp_id}")
        # leave the worktree in place so the founder can inspect; caller/founder removes after merge
        return {"accepted": True, "landed": landed, "branch": branch, "pr": pr_url, "worktree": wt,
                "receipt": rec, "patch": patch, "reason": "verified", "integrity": integrity,
                "checkpoint": checkpoint, "usage": spend, "route_id_selected": route_id_selected,
                "model_requested": model, "model_actual": spend.get("model")}
    except BaseException as e:  # noqa: BLE001 — also covers operator aborts (KeyboardInterrupt/SystemExit),
        # not just Exception subclasses, so an interrupted run is receipted the same as any other fault.
        # final_outcome=ERROR (or ABORT for a non-Exception signal): an unexpected fault or operator abort,
        # not a clean test/integrity verdict. Mint a best-effort receipt so the failure is RECORDED
        # (tamper-evident, with the metering captured so far) before we roll back and re-raise — this
        # disposition must never be a silent gap in the receipt chain.
        final_outcome = "ERROR" if isinstance(e, Exception) else "ABORT"
        try:
            H._receipt(repo, task, test_cmd, {"outcome": "error", "exit_code": None}, patch, usage=spend,
                       metering={"attempt_number": attempt_number,
                                 "empty_response_retries": empty_response_retries, "checkpoint_id": None,
                                 "route_id_selected": route_id_selected,
                                 "evidence_result": f"unexpected error: {type(e).__name__}: {str(e)[:200]}",
                                 "final_outcome": final_outcome})
        except Exception:  # noqa: BLE001 — receipt bookkeeping must never mask the original fault
            pass
        H.discard(repo, wt)
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--test", required=True, dest="test_cmd")
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--base", default="HEAD",
                    help="clean-room base ref (default HEAD); 'last-healthy' resolves to the last healthy L4 checkpoint")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--no-pr", action="store_true")
    ap.add_argument("--model", default=None, help="pin the model (e.g. claude-opus-4-8); records + warns on mismatch")
    ap.add_argument("--result-cache", action="store_true",
                    help="opt-in: reuse a prior accepted patch+receipt on an EXACT fingerprint match (skips the model)")
    ap.add_argument("--no-route", action="store_true",
                    help="disable ECP route auto-select (kill-switch; same as SEIF_NO_ROUTE=1)")
    ap.add_argument("--protected", action="append", default=None, metavar="PATTERN",
                    help="founder-approved protected-set override for tasks that legitimately add/edit tests: "
                         "repeatable; each use supplies one protected path (same vocabulary as the default "
                         "PROTECTED tuple: dir prefixes ending in '/', fnmatch globs, exact paths). Given at "
                         "least once, the supplied set REPLACES the default PROTECTED tuple; absent, the "
                         "default applies unchanged. Gate-bypass sentinels stay enforced regardless "
                         "(integrity_guard enforces them unconditionally).")
    a = ap.parse_args()
    # auto-select is the default (route=None). --no-route flips the kill-switch (route=False).
    kw = {}
    if a.protected is not None:
        kw["protected"] = tuple(a.protected)
    r = seif_run(a.repo, a.task, a.test_cmd, budget=a.budget, base=a.base, timeout=a.timeout,
                 make_pr=not a.no_pr, model=a.model, route=False if a.no_route else None,
                 result_cache=(True if a.result_cache else None), **kw)
    sys.exit(0 if r["accepted"] else 1)


def _selftest():
    """Real git repo + injected editor (no LLM): the integrity gate must REJECT a test-editing 'pass'
    and ACCEPT an honest source fix, leaving main untouched."""
    import tempfile
    import textwrap
    global _claude_edit
    repo = tempfile.mkdtemp(prefix="seif-run-")
    CP.LEDGER = os.path.join(repo, "_checkpoints.jsonl")          # temp registries — don't touch the real ledger
    CP.FAILURES = os.path.join(repo, "_failures.jsonl")
    g = lambda *a: subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                  check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", repo], check=True)
    open(os.path.join(repo, "calc.py"), "w").write("def add(a, b):\n    return a - b\n")   # bug
    open(os.path.join(repo, "test_calc.py"), "w").write(textwrap.dedent("""\
        import unittest
        from calc import add
        class T(unittest.TestCase):
            def test_add(self):
                self.assertEqual(add(2, 3), 5)
        """))
    g("add", "-A"); g("commit", "-qm", "base")
    cmd = f"{sys.executable} -m unittest -q test_calc"
    orig = _claude_edit
    try:
        # case 1: CHEAT by rewriting the test to trivially pass -> integrity gate must reject
        def cheat(wt, *a, **k):
            open(os.path.join(wt, "test_calc.py"), "w").write(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
            return 0, UM.empty()                          # (rc, usage) — new instrumented contract
        _claude_edit = cheat
        r1 = seif_run(repo, "make tests pass", cmd, budget=1, base="HEAD", make_pr=False)
        assert not r1["accepted"] and r1["reason"] == "integrity_violation", r1
        assert any(h["file"].endswith("test_calc.py") for h in r1["integrity"]["hard"]), r1["integrity"]
        # rejection recorded ASRS failure forensics (no checkpoint created for an unverified state)
        fails = CP._read(CP.FAILURES)
        assert fails and fails[-1]["failure_reason"] == "integrity_violation", fails
        assert CP.last_healthy(repo) is None, "no checkpoint may exist before any verified run"

        # case 2: HONEST source fix -> accepted, lands on a local branch (no remote)
        def honest(wt, *a, **k):
            open(os.path.join(wt, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
            return 0, UM.empty()                          # (rc, usage) — new instrumented contract
        _claude_edit = honest
        r2 = seif_run(repo, "fix add", cmd, budget=1, base="HEAD", make_pr=False)
        assert r2["accepted"] and r2["reason"] == "verified", r2
        # L4: the verified run registered a healthy checkpoint (commit + proof + context)
        assert r2["checkpoint"] and r2["checkpoint"]["proof"]["outcome"] == "pass", r2["checkpoint"]
        lh = CP.last_healthy(repo)
        assert lh and lh["id"] == r2["checkpoint"]["id"], "verified run must become the last healthy checkpoint"
        assert "calc.py" in lh["context"]["files_changed"], lh["context"]
        assert CP.verify_chain(CP.LEDGER)[0], "checkpoint chain must verify"
        H.discard(repo, r2["worktree"])
        # main never touched (still the buggy version)
        assert open(os.path.join(repo, "calc.py")).read().strip().endswith("a - b"), "main untouched"
        print("seif_run selftest PASS — integrity gate REJECTS test-editing, ACCEPTS honest fix; "
              "verified run mints a healthy L4 checkpoint; rejection records ASRS forensics; main untouched")
    finally:
        _claude_edit = orig
        import shutil
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
