# Findings — Load Architecture (Round 3, MEASURED 2026-06-24)

The reframe (2026-06-24): **the dominant Claude Code token lever is LOAD architecture** — what enters every
call — not graph retrieval. Round 3 decomposes the per-call environment tax by SOURCE, holding task + model
constant and varying only what the `claude` CLI loads. Bench: `logos/loadarch_bench.py`; raw artifact:
`docs/receipts/2026-06-24-token-economics-round3.json`. Builds on E1–E4 (`docs/FINDINGS_TOKEN_ECONOMICS.md`).

## The Context Bill of Materials (CBOM) — per-arm fresh input (n=2 tasks × 2 seeds)

| Arm | flags | mean fresh input | model |
| --- | --- | --- | --- |
| full | (default) | 31,679 | opus |
| noMCP | `--strict-mcp-config` | 18,077 | opus |
| noUser | `--setting-sources project` | 14,681 | mostly haiku (downgrade) |
| bare | `--bare` | **FAILED** (empty 4/4) | none |

## Env-tax decomposition (fresh input is ~model-independent)

The ~31.7K fresh-input tax per call breaks down as:

| Source | fresh tokens/call | share | how isolated |
| --- | --- | --- | --- |
| **User `CLAUDE.md` + skills + hooks** | **~17,000** | ~54% | full − noUser |
| **MCP tool schemas** | **~13,600** | ~43% | full − noMCP |
| Irreducible base (system prompt + core tools) | ~2,500 | ~3% | E1 full-lean floor |

Cross-check: 17.0K + 13.6K + 2.5K ≈ 33K ≈ full (31.7K), within noise. The E1 full-lean profile
(`--strict-mcp-config --setting-sources project`, both stripped) measured ~2.5K fresh input — i.e. the
floor once BOTH big sources are removed (−92% vs full).

## What this means (actionable for the ECP profile)

1. **MCP is a major, cuttable tax on agentic tasks (~13.6K fresh/call, ~43%).** The trivial-call probe
   showed only ~540 — because agentic tasks load *all* MCP tool schemas. Lean worker calls should pass
   `--strict-mcp-config` and load only the MCP a task's route actually needs.
2. **User `CLAUDE.md` + skills + hooks is the largest single source (~17K, ~54%).** Trimming the global
   `~/.claude/CLAUDE.md` and gating skills/hooks to where they're relevant is the biggest lever — and it is
   **founder-gated** (runtime self-modification of the global environment). Round 3 is the *evidence* for
   the cut; the cut is the founder's call.
3. **The usable lean profile is `--strict-mcp-config --setting-sources project`** → ~2.5K fresh input,
   still resolves. **`--bare` is NOT usable for agentic edit tasks** — it returned an empty envelope every
   time (4/4, even with retry-on-empty), so the earlier "--bare workers" idea does not hold as-is. The
   minimal-but-working worker profile is the two strip-flags, not `--bare`.

## Validations

- **Model-mismatch guard fired 7/16** (`--setting-sources project` silently downgraded opus→haiku on
  agentic tasks; `--bare` returned no model). This is exactly the silent-downgrade the production guard
  (PR #35) now records + warns on — round 3 is its real-world justification.
- **Fresh input is model-independent**, so the decomposition holds despite the noUser arm running haiku
  (we measure token *counts*, not pricing, for the env breakdown).

## Honest limits

- n=2 tasks × 2 seeds, one fixture; directional, not a CI-backed law.
- `--bare` failed, so the "total tax via full−bare" field in the raw artifact is not meaningful; the true
  floor is the E1 full-lean (~2.5K), and the tax is full − that ≈ ~29K.
- noUser ran haiku (model downgrade) — fine for the fresh-input *count* decomposition, not for its cost.

## Next

- Feed this into the **ECP Engineering Context Profile**: lean `CLAUDE.md` (founder-gated) + path-specific
  rules + route-scoped MCP allowlists, then re-measure the realized per-call savings.
- More seeds + a per-source CI; quantify MCP savings per route (load only needed servers).
