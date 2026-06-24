#!/usr/bin/env python3
"""ECP route compiler (Engineering Context Profile v0.1).

The keystone of the load-architecture thesis: compile a declarative route manifest (`efl.route/v1`) into
the MINIMUM operating environment for a task — the lean `claude` invocation, the scoped context packet, the
tool/MCP policy, the budget, and the verification contract. This is the machine-readable layer that turns
the measured levers into per-task policy:

  - Lever 1 (load, −92% fresh input): drop the always-loaded user environment via `--setting-sources project`
    + `--strict-mcp-config`; pull in only the route's MCP servers.
  - Lever 2 (model, −70/−86%): route to the cheapest capable model; default-cheap, escalate only on measured
    failure (Round-3 finding — dynamic routing is not yet justified, so the default IS the cheap model).

MEASURED CONSTRAINT honestly encoded: `--setting-sources project` (the ~54% lever) also forces the agentic
model down to the cheap default — you cannot have lean-context AND a pinned strong model via these flags.
So `compile_route` derives flags from the route's model intent:
  - cheap/default model  -> FULL lean (setting-sources project + strict-mcp) = max saving.
  - pinned strong model  -> keep user settings (no 54% via this flag) + strict-mcp (still the ~43% lever).

This module is pure + dependency-light: `compile_route` operates on a plain dict (no I/O, no yaml), so it is
fully unit-testable; `load_route` is a thin yaml loader. It does NOT execute claude — it produces the
compiled spec the loop consumes.
"""
import collections

SCHEMA = "efl.route/v1"

# requested_model aliases -> concrete, verified model ids (pricing/ids verified live 2026-06-24).
MODEL_IDS = {
    "claude-haiku": "claude-haiku-4-5-20251001",
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-opus": "claude-opus-4-8",
}
# Models that the lean `--setting-sources project` path serves as the agentic default (the cheap tier).
# Pinning one of these is compatible with FULL lean; pinning a stronger model is not (see module docstring).
LEAN_DEFAULT_MODELS = {"claude-haiku-4-5-20251001"}


def resolve_model(requested):
    """Map a requested_model alias to a concrete id; pass through an already-concrete id; None -> cheap default."""
    if not requested:
        return MODEL_IDS["claude-haiku"]
    return MODEL_IDS.get(requested, requested)


def validate_route(route):
    """Return a list of problems (empty = valid). Cheap structural validation, not a full JSON-schema."""
    problems = []
    if not isinstance(route, dict):
        return ["route must be a mapping"]
    if route.get("schema") != SCHEMA:
        problems.append(f"schema must be '{SCHEMA}' (got {route.get('schema')!r})")
    if not route.get("id"):
        problems.append("missing 'id'")
    # sub-objects, when present, must be mappings — fail cleanly here rather than AttributeError later
    for key in ("match", "context", "tools", "budget", "memory", "verification"):
        if key in route and route[key] is not None and not isinstance(route[key], dict):
            problems.append(f"'{key}' must be a mapping")
    match = route.get("match")
    if isinstance(match, dict) and not (match.get("intents") or match.get("paths")):
        problems.append("match must declare at least one of intents/paths")
    elif not isinstance(match, dict):
        problems.append("missing or invalid 'match'")
    tools = route.get("tools")
    if isinstance(tools, dict):
        for k in ("allow", "deny", "mcp"):
            if k in tools and not isinstance(tools[k], list):
                problems.append(f"tools.{k} must be a list")
    return problems


def _forward_or_reverse_closure(graph, seeds, edges, max_hops, direction):
    """Closure of seeds over `graph` (graphify-out shape: nodes[{id,source_file}], links[{source,target,relation}]).
    direction 'fwd' walks source->target; 'rev' walks target->source. Returns sorted source_files."""
    if not isinstance(graph, dict):
        return sorted(set(seeds))
    raw_nodes = graph.get("nodes"); raw_links = graph.get("links")
    nodes = [n for n in raw_nodes if isinstance(n, dict)] if isinstance(raw_nodes, list) else []
    links = [l for l in raw_links if isinstance(l, dict)] if isinstance(raw_links, list) else []
    by_file = {n.get("source_file"): n.get("id") for n in nodes if n.get("source_file")}
    id_file = {n.get("id"): n.get("source_file") for n in nodes}
    adj = collections.defaultdict(list)
    for l in links:
        if edges and l.get("relation") not in edges:
            continue
        if direction == "fwd":
            adj[l.get("source")].append(l.get("target"))
        else:
            adj[l.get("target")].append(l.get("source"))
    out, seen, frontier = set(), set(), collections.deque()
    for s in seeds:
        nid = by_file.get(s)
        if nid:
            frontier.append((nid, 0)); seen.add(nid)
        out.add(s)
    while frontier:
        nid, d = frontier.popleft()
        if d >= max_hops:
            continue
        for nxt in adj.get(nid, []):
            if nxt not in seen:
                seen.add(nxt)
                if id_file.get(nxt):
                    out.add(id_file[nxt])
                frontier.append((nxt, d + 1))
    return sorted(out)


def _resolve_context(route, changed_files, graph):
    """Resolve the context packet: literal required files + any graph selector closures over changed_files."""
    ctx = route.get("context"); ctx = ctx if isinstance(ctx, dict) else {}
    req = ctx.get("required")
    files = list(req) if isinstance(req, list) else []
    selectors = ctx.get("selectors")
    selectors = selectors if isinstance(selectors, list) else []
    unresolved = []
    for sel in selectors:
        g = sel.get("graph") if isinstance(sel, dict) else None
        if not isinstance(g, dict):            # a non-dict selector graph is ignored, not crashed on
            continue
        raw_seeds = g.get("seeds")
        if raw_seeds in ("${changed_files}", None):
            seeds = list(changed_files)
        else:
            seeds = list(raw_seeds) if isinstance(raw_seeds, list) else []
        edges = set(g.get("edges")) if isinstance(g.get("edges"), list) else set()
        try:
            hops = int(g.get("max_hops") or 1)
        except (TypeError, ValueError):
            hops = 1
        if graph and seeds:
            files += _forward_or_reverse_closure(
                graph, seeds, edges, hops, "rev" if "imports" in edges else "fwd")
        else:
            # no graph available (or no seeds) → cannot expand; record the intent, fall back to seeds
            files += seeds
            unresolved.append({"selector": "graph", "reason": "no graph provided" if not graph else "no seeds"})
    # de-dupe, preserve order
    seen, ordered = set(), []
    for f in files:
        if f not in seen:
            seen.add(f); ordered.append(f)
    return ordered, unresolved


def compile_route(route, changed_files=None, graph=None):
    """Compile a route manifest into the minimum operating environment. Returns a plain dict (no I/O).

    Keys: model, lean (bool/full), claude_argv, context_files, context_unresolved, tool_policy,
    mcp_allow, budget, verification, memory, warnings.
    """
    problems = validate_route(route)
    if problems:
        raise ValueError("invalid route: " + "; ".join(problems))

    changed_files = changed_files or []
    # defense in depth: validate_route already flagged non-dict sub-objects, but guard here too so a None
    # (= "absent", legitimately valid) or anything that slipped through can never raise mid-compile.
    _d = lambda k: route.get(k) if isinstance(route.get(k), dict) else {}
    budget = _d("budget")
    model = resolve_model(budget.get("requested_model"))
    tools = _d("tools")
    mcp_allow = list(tools.get("mcp") or [])
    warnings = []

    # ---- lever derivation (honest, measured) ----
    # `extras` = the lean flags AFTER `--model <model>`; tracked separately so the loop can apply them
    # without re-deriving (lean_flags in the return). claude_argv = core + model + extras.
    extras = []
    # MCP is always scoped: strict-mcp-config drops all ambient MCP (~43% lever); the route's mcp list is
    # what the loop should re-add via --mcp-config (the only servers this task needs).
    extras.append("--strict-mcp-config")
    if model in LEAN_DEFAULT_MODELS:
        # FULL lean: also drop the user environment (~54% lever). Compatible with the cheap default model.
        extras += ["--setting-sources", "project"]
        lean = "full"
    else:
        # Pinned strong model: --setting-sources project would force a downgrade (measured), so we keep user
        # settings here. Still get the MCP lever; not the user-config lever. State the tradeoff.
        lean = "mcp-only"
        warnings.append(
            f"model '{model}' is not the lean default — keeping user settings to honor it, so the ~54% "
            "user-config saving does not apply (only the ~43% MCP saving). Route to the cheap default for full lean.")
    if tools.get("allow"):
        extras += ["--allowedTools", *list(tools["allow"])]
    if tools.get("deny"):
        extras += ["--disallowedTools", *list(tools["deny"])]
    base = ["-p", "--output-format", "json", "--permission-mode", "acceptEdits", "--model", model] + extras

    context_files, unresolved = _resolve_context(route, changed_files, graph)

    return {
        "route_id": route.get("id"),
        "model": model,
        "lean": lean,
        "claude_argv": base,
        "lean_flags": extras,
        "context_files": context_files,
        "context_unresolved": unresolved,
        "tool_policy": {"allow": list(tools.get("allow") or []), "deny": list(tools.get("deny") or [])},
        "mcp_allow": mcp_allow,
        "budget": {"max_turns": budget.get("max_turns"),
                   "max_fresh_input_tokens": budget.get("max_fresh_input_tokens"),
                   "max_wall_seconds": budget.get("max_wall_seconds")},
        "verification": dict(_d("verification")),
        "memory": dict(_d("memory")),
        "warnings": warnings,
    }


def load_route(path):
    """Thin yaml loader (kept separate so compile_route stays pure + dependency-free)."""
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


def _glob_match(path, pattern):
    """Globstar-aware match: `**` spans directories (incl. none), `*` stays within a segment, `?` one char.
    (Python's fnmatch treats `*` as crossing `/`, so `logos/**/*.py` wouldn't match the direct child
    `logos/x.py`; this does.)"""
    import re
    out, k = "", 0
    while k < len(pattern):
        if pattern[k:k + 3] == "**/":
            out += "(?:.*/)?"; k += 3          # zero-or-more directory segments
        elif pattern[k:k + 2] == "**":
            out += ".*"; k += 2
        elif pattern[k] == "*":
            out += "[^/]*"; k += 1
        elif pattern[k] == "?":
            out += "[^/]"; k += 1
        else:
            out += re.escape(pattern[k]); k += 1
    return re.fullmatch(out, path) is not None


def match_route(routes, intent=None, path=None):
    """Pick the first route whose match declares the given intent and/or whose paths glob-match `path`."""
    for r in routes:
        m = r.get("match") or {}
        if intent and intent not in (m.get("intents") or []):
            continue
        if path and not any(_glob_match(path, g) for g in (m.get("paths") or [])):
            continue
        if intent or path:
            return r
    return None


if __name__ == "__main__":
    import json
    import sys
    route = load_route(sys.argv[1])
    print(json.dumps(compile_route(route, changed_files=sys.argv[2:] or None), indent=2))
