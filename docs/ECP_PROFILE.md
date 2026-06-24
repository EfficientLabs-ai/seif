# ECP — Engineering Context Profile v0.1

The machine-readable layer that turns the **load-architecture** findings into per-task policy. The measured
thesis (see `docs/FINDINGS_TOKEN_ECONOMICS.md`, `docs/FINDINGS_LOAD_ARCHITECTURE.md`):

> The dominant token lever is **what enters every call** — not graph retrieval. Strip the always-loaded
> environment and route to the cheapest capable model; verify outside the model.

ECP makes that operational: a task is matched to a **route**, and the route is **compiled** into the
*minimum operating environment* for that task — the lean `claude` invocation, the scoped context packet, the
tool/MCP policy, the budget, and the verification contract.

## Pieces (v0.1)

| Piece | Status | What |
| --- | --- | --- |
| Route manifest (`efl.route/v1`) | **WIRED** | declarative per-task-class policy — `01_routes/*.yaml` |
| Route compiler (`logos/ecp_route.py`) | **WIRED** | `compile_route()` → lean argv + context packet + tool/MCP policy + budget + verification (pure, unit-tested) |
| Path-specific rules (`.claude/rules/`) | TARGET | native Claude Code per-path instructions (load only when working matching files) |
| On-demand skills | TARGET | procedures that don't load every session |
| Lean global `~/.claude/CLAUDE.md` | **FOUNDER-GATED** | the ~54% lever — proposal in `docs/proposals/lean-claude-md.md` |
| Loop integration (compiler → `seif_run`) | TARGET | the loop consumes the compiled spec |

## The measured levers, encoded honestly

`compile_route()` derives the lean `claude` flags from the route's model intent, encoding the **measured
constraint** that `--setting-sources project` (the ~54% user-config saving) also forces the agentic model to
the cheap default — so lean-context and a pinned strong model **cannot coexist** via these flags:

- **cheap default model → FULL lean:** `--strict-mcp-config` (≈43% MCP saving) **+** `--setting-sources project`
  (≈54% user-config saving). Round-3 measured the cheap model matches resolution at −86% cost with zero
  false accepts, so the **default IS the cheap model** — dynamic routing/escalation is *not yet* justified.
- **pinned strong model → MCP-only lean:** keep user settings (to honor the model) + `--strict-mcp-config`.
  Gets the ~43% lever, not the ~54% one. The compiler emits a `warning` stating the tradeoff — it is never
  hidden.

It also scopes MCP (only the route's `mcp:` servers), turns `tools.allow`/`deny` into `--allowedTools` /
`--disallowedTools`, and resolves the context packet (required files + graph-selector closure over the
changed files, degrading gracefully to the seeds when no graph is available).

## Route manifest schema (`efl.route/v1`)

```yaml
schema: efl.route/v1
id: <route-id>
match:    { intents: [...], paths: ["glob/**/*.py"] }   # ** spans directories
context:  { required: [files], selectors: [{graph: {seeds: "${changed_files}", edges: [imports], max_hops: 2}}] }
tools:    { allow: [...], deny: [...], mcp: [...] }
memory:   { working: {backend, ttl_seconds}, episodic: {...}, graph: {...}, checkpoint: {required_before_mutation} }
budget:   { requested_model: claude-haiku|claude-sonnet|claude-opus, max_turns, max_fresh_input_tokens, max_wall_seconds }
verification: { commands: [...], checkpoint_on: [...], human_approval: [...] }
```

Compile it: `python3 logos/ecp_route.py 01_routes/<route>.yaml <changed_files...>`.

## Directory convention (TARGET — not imposed on this repo yet)

The full ECP layout (`00_truth/ 01_routes/ 02_workspaces/ … 09_receipts/`) is the **target** for repos that
adopt ECP wholesale. This repo adopts it incrementally: `01_routes/` exists now; the rest map onto existing
folders (`docs/` ≈ truth/reference, `docs/receipts/` = receipts, `logos/` = the engine). A full reorg is a
separate, founder-gated decision — ECP works as an additive layer without it.

## Governance

The YAML route layer is **our extension** — the public ICM/MWP methodology (Van Clief & McDermott) is
folder + Markdown-contract based; the machine-readable routing is Efficient Labs'. The route manifest is a
*specification* the loop compiles into enforcement; hard controls remain hooks + permission settings + the
SEIF gate, never the manifest text. Changes to routes go through the normal branch → tests → review → PR →
founder-merge flow.
