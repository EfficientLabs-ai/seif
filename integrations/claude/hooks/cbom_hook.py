#!/usr/bin/env python3
"""SEIF Context Bill of Materials — SessionStart hook (NOT installed; repo-only).

What it does: at session start, it itemizes what every subsequent `claude` call will silently load — the
user + project CLAUDE.md files, skills, plugins, hooks, and MCP servers — attaches an approximate token size
to each, and writes a CBOM JSON to `logos/cbom/<timestamp>.json`. That turns the ~17K "user-config tax" the
loadarch benchmark measures in aggregate into a per-item breakdown the founder can read and decide what to
gate. The static counts here pair with the live subtraction in `logos/loadarch_bench.py`.

How it runs (when the founder chooses to install it — this repo only ADDS the script, it never copies it
into ~/.claude, which is founder-gated):
    SessionStart hook → bash → `python integrations/claude/hooks/cbom_hook.py`
Claude Code passes a JSON payload on stdin ({session_id, transcript_path, cwd, hook_event_name, source}).
This script reads that payload to tag the CBOM with the session, but DEGRADES SAFELY if stdin is absent,
empty, or non-JSON — a SessionStart hook must never block or slow a session, so every step is wrapped and
any failure falls through to "write what we have, exit 0".

Discovery is READ-ONLY: it stats/reads files under $HOME/.claude and the project, computes sizes with the
heuristic in `logos/cbom.py`, and writes ONE output file into the repo. It installs nothing and mutates no
config. Pure stdlib; no third-party imports.
"""
import datetime
import json
import os
import sys

# Make logos/cbom.py importable whether invoked from the repo root or elsewhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_LOGOS = os.path.join(_REPO_ROOT, "logos")
for _p in (_LOGOS, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import cbom as CBOM  # noqa: E402
except Exception:  # noqa: BLE001 — if the module can't load, the hook still must not crash a session
    CBOM = None


def _read_stdin_payload():
    """Best-effort parse of the SessionStart JSON payload on stdin. Returns a dict (possibly empty).
    Never blocks on a TTY and never raises — absent/empty/non-JSON stdin → {}."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        obj = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return obj if isinstance(obj, dict) else {}


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _claude_dir():
    """The user-config directory Claude Code loads from ($CLAUDE_CONFIG_DIR, else ~/.claude)."""
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(_home(), ".claude")


def _add_file_item(items, kind, name, path):
    """Append a CBOM item for a real file (token + byte size from disk). Missing file → skipped."""
    if CBOM is None or not path or not os.path.isfile(path):
        return
    tok, nbytes = CBOM.estimate_file_tokens(path)
    items.append(CBOM.make_item(kind, name, tokens=tok, path=path, bytes_=nbytes))


def _scan_md_files(items, kind, root, max_files=200):
    """Add an item per *.md found under `root` (skills / plugin docs are markdown). Bounded + no-throw."""
    if not root or not os.path.isdir(root):
        return
    n = 0
    try:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.lower().endswith(".md"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                _add_file_item(items, kind, rel, full)
                n += 1
                if n >= max_files:
                    return
    except Exception:  # noqa: BLE001
        return


def _scan_mcp(items, settings):
    """Add one item per configured MCP server. We don't have live schema token counts at session start, so
    each server's size is approximated from its own config blob (a stable, cheap proxy for its surface)."""
    servers = settings.get("mcpServers") if isinstance(settings, dict) else None
    if not isinstance(servers, dict) or CBOM is None:
        return
    for name, cfg in servers.items():
        try:
            blob = json.dumps(cfg, sort_keys=True)
        except Exception:  # noqa: BLE001
            blob = str(cfg)
        items.append(CBOM.make_item("mcp", str(name), tokens=CBOM.estimate_tokens(blob)))


def _scan_hooks(items, settings):
    """Add one item per configured hook command (the command strings themselves enter no context, but the
    inventory is what the founder wants to see — which hooks are wired)."""
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict) or CBOM is None:
        return
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for grp in groups:
            for h in (grp.get("hooks", []) if isinstance(grp, dict) else []):
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                items.append(CBOM.make_item("hook", f"{event}:{(cmd or '')[:60]}",
                                            tokens=CBOM.estimate_tokens(cmd)))


def _read_settings(claude_dir):
    """Merge user settings.json + settings.local.json (local overrides). No-throw → {}."""
    merged = {}
    for fn in ("settings.json", "settings.local.json"):
        p = os.path.join(claude_dir, fn)
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                merged.update(d)
        except Exception:  # noqa: BLE001
            continue
    return merged


def build_items(payload):
    """Walk the (read-only) config surface and return a list of CBOM items. Each step is independent and
    no-throw, so a failure in one source never drops the rest."""
    items = []
    if CBOM is None:
        return items
    home = _home()
    claude_dir = _claude_dir()
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if not (isinstance(cwd, str) and os.path.isdir(cwd)):
        try:
            cwd = os.getcwd()  # can raise if the cwd was deleted out from under us
        except Exception:  # noqa: BLE001 — fall back to the repo root rather than raise out of the hook
            cwd = _REPO_ROOT
    project = cwd

    # 1) CLAUDE.md files (user-level + project-level + nested-memory) — the headline user-config tax.
    _add_file_item(items, "user_config", "~/.claude/CLAUDE.md", os.path.join(claude_dir, "CLAUDE.md"))
    _add_file_item(items, "user_config", "~/CLAUDE.md", os.path.join(home, "CLAUDE.md"))
    _add_file_item(items, "user_config", "<project>/CLAUDE.md", os.path.join(project, "CLAUDE.md"))
    _add_file_item(items, "user_config", "<project>/.claude/CLAUDE.md",
                   os.path.join(project, ".claude", "CLAUDE.md"))

    # 2) skills (user + project) — one item per skill markdown.
    _scan_md_files(items, "skill", os.path.join(claude_dir, "skills"))
    _scan_md_files(items, "skill", os.path.join(project, ".claude", "skills"))

    # 3) plugins — one item per plugin doc markdown under the plugin cache.
    _scan_md_files(items, "plugin", os.path.join(claude_dir, "plugins"))

    # 4) hooks + 5) MCP servers — from merged settings.
    settings = _read_settings(claude_dir)
    _scan_hooks(items, settings)
    _scan_mcp(items, settings)
    return items


def build_cbom(payload, items=None):
    """Assemble the full CBOM dict, tagged with session metadata from the hook payload (when present)."""
    if items is None:
        items = build_items(payload)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    session = {}
    if isinstance(payload, dict):
        for k in ("session_id", "hook_event_name", "source", "cwd"):
            if k in payload:
                session[k] = payload[k]
    if CBOM is None:
        return {"version": "0.1", "generated_at": now, "items": list(items), "session": session}
    return CBOM.make_cbom(items, generated_at=now, session=session)


def _timestamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def output_path():
    """Where the CBOM is written: logos/cbom/<timestamp>.json under the repo. Created if absent."""
    out_dir = os.path.join(_LOGOS, "cbom")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:  # noqa: BLE001
        out_dir = "."  # last-resort fallback; still never raises
    return os.path.join(out_dir, f"{_timestamp()}.json")


def write_cbom(cbom, path=None):
    """Write the CBOM JSON. Returns the path on success, or None on any failure (no-throw)."""
    path = path or output_path()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cbom, fh, indent=2, sort_keys=True)
        return path
    except Exception:  # noqa: BLE001
        return None


def main():
    """Entry point. ALWAYS exits 0 — a SessionStart hook must never block a session. Writes the CBOM and
    prints a one-line summary to stderr (hook stdout is reserved for context the model would ingest)."""
    payload = _read_stdin_payload()
    try:
        cbom = build_cbom(payload)
        path = write_cbom(cbom)
        if CBOM is not None:
            line = CBOM.summary_line(cbom)
        else:
            line = f"CBOM (degraded): {len(cbom.get('items', []))} item(s)"
        sys.stderr.write(f"[cbom] {line}" + (f" -> {path}" if path else " (write failed)") + "\n")
    except Exception as e:  # noqa: BLE001 — absolutely no exception may escape a SessionStart hook
        sys.stderr.write(f"[cbom] skipped: {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
