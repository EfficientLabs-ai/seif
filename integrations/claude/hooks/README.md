# Claude Code hooks — repo-only scripts (install is founder-gated)

These scripts bind to Claude Code's hook events but are **not installed** by this repo — copying anything
into `~/.claude` (settings, hooks, commands) is a founder-gated, irreversible-config action. The repo only
*adds the script*; wiring it into a session is the founder's call.

## `cbom_hook.py` — Context Bill of Materials (SessionStart)

Itemizes what every `claude` call silently loads — user/project `CLAUDE.md`, skills, plugins, hooks, MCP
servers — and writes a per-item token breakdown to `logos/cbom/<timestamp>.json`. This turns the aggregate
"user-config tax" that `logos/loadarch_bench.py` measures by subtraction into a line-by-line inventory the
founder can read to decide what to gate. The scan is **read-only**: it stats/reads config files and writes
one output file; it installs nothing and mutates no config. It always exits 0 (a SessionStart hook must
never block a session) and degrades safely if the stdin payload is absent.

Try it without a live session (no payload → it scans the current config surface and writes a CBOM):

```bash
echo '{}' | python integrations/claude/hooks/cbom_hook.py
python logos/cbom.py logos/cbom/<timestamp>.json    # one-line summary of any CBOM file
```

To install (FOUNDER-GATED — do not let an agent do this), add a SessionStart hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "*",
        "hooks": [ { "type": "command",
                     "command": "python /home/neo/seif/integrations/claude/hooks/cbom_hook.py" } ] }
    ]
  }
}
```

The pure inventory/accounting logic lives in `logos/cbom.py` (`parse`, `summarize`, `estimate_tokens`) and
is unit-tested in `tests/test_cbom.py` over a fixture CBOM — no live session needed.
