"""Gate-bypass-sentinel DETECTOR for live tool actions (seif issue #21).

Companion to integrity_guard.py: the guard scans a *candidate diff* before a PR; this detector
classifies a *live tool action* ({'tool','path','in_clean_room'}) the moment it happens, so a
PostToolUse hook can refuse a write that drops a `.seif-gate-off` sentinel onto the real
filesystem (switching the SEIF Stop-hook gate OFF — reward-hacking). A `.seif-gate-off` *inside*
a clean room is legitimate (the clean room intentionally bypasses the interactive Stop hook; its
real test suite IS the gate), so it is NOT flagged.

Matching mirrors integrity_guard: the basename is compared case-insensitively, after expanding a
leading `~`, normalizing backslashes, and discarding any subdirectory — so case/subdir/`~` variants
of the sentinel are all caught.

TODO: wire this into a PostToolUse hook under ~/.claude. That edit is FOUNDER-GATED — it is a
runtime self-modification of the harness (the agent altering its own guardrails) and per AUTH.md /
the founder-gate model must not be performed autonomously. This module is the pure, testable core;
the hook glue is deliberately out of scope here.
"""

import os

# Gate-disabling sentinel basenames that must NEVER be written to the real filesystem. A live action
# that creates/writes one OUTSIDE a clean room is trying to switch the gate OFF. Kept as a tuple to
# mirror integrity_guard._BYPASS_SENTINELS and to allow future siblings.
_BYPASS_SENTINELS = (".seif-gate-off",)

# Tools that unambiguously CREATE/WRITE the named path (a read/list/delete does not disable the gate).
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _basename(path):
    """Lowercased final path segment, after expanding a leading '~' and normalizing backslashes.

    Mirrors integrity_guard's case-insensitive, subdir-tolerant matching so case/subdir/'~' variants
    of a sentinel all reduce to the same basename."""
    p = os.path.expanduser((path or "").strip())
    p = p.replace("\\", "/").rstrip("/")          # backslashes -> /, drop trailing slash
    return p.rsplit("/", 1)[-1].lower()


def classify_action(action):
    """Classify a single live tool action for the gate-bypass-sentinel vector.

    action = {'tool': str, 'path': str, 'in_clean_room': bool}. Returns a dict with 'severity'
    'high' (+ 'vector' == 'gate_bypass_sentinel' and a 'reason') when the action creates/writes a
    file whose basename is a bypass sentinel OUTSIDE a clean room (in_clean_room False). A normal
    write, OR a clean-room-internal sentinel (in_clean_room True), is 'severity' 'none'."""
    action = action or {}
    tool = action.get("tool", "")
    path = action.get("path", "")
    in_clean_room = bool(action.get("in_clean_room", False))
    base = _basename(path)
    # Only a CREATE/WRITE drops a gate-disabling file; a read/list/delete of one is not a gate-disable.
    # Unambiguous writers by tool name, plus an explicit `writes` flag for Bash (where the path alone
    # can't tell intent — the caller marks a command that creates/writes the sentinel).
    is_write = tool in _WRITE_TOOLS or bool(action.get("writes"))

    if base in _BYPASS_SENTINELS and not in_clean_room and is_write:
        return {
            "severity": "high",
            "vector": "gate_bypass_sentinel",
            "reason": ("tool %r writes gate-disabling sentinel %r outside a clean room — "
                       "refuses to let the SEIF gate be switched OFF" % (tool, path)),
        }
    return {"severity": "none", "vector": "gate_bypass_sentinel", "reason": "no gate-bypass sentinel write detected"}
