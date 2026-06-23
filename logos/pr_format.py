#!/usr/bin/env python3
"""SEIF PR + commit formatting — one professional, scannable house style for everything in GitHub.

Pure stdlib builders that the loop (`seif_run`) and manual PRs both call, so every PR reads the same way:
a bold one-line banner with status chips, an at-a-glance **Verification** table, a **Changes** table, a
collapsible **Evidence** block (verbose output stays out of the way), the issue link, and the founder-gate
footer. Commits follow conventional-commits. Deterministic, dependency-free — so the rendered markdown is
testable and identical whether a cron, the loop, or a human triggers it.
"""

PROVENANCE = "🤖 SEIF autonomous loop · generated with [Claude Code](https://claude.com/claude-code)"


def chip(ok, label):
    """A status chip: ✅ on success, ⚠️ otherwise."""
    return f"{'✅' if ok else '⚠️'} {label}"


def _cell(x):
    """Escape a value for a markdown table cell — collapse newlines and escape `|` so untrusted text
    (task descriptions, test commands, odd filenames) can never break the table structure."""
    return str(x).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def _table(rows, headers):
    out = ["| " + " | ".join(_cell(h) for h in headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _vrow(row):
    """Coerce a verification entry to a (check, result, ok) triple so a malformed or short tuple
    (e.g. ``("Tests",)`` or a bare string) renders instead of crashing the whole PR body."""
    seq = list(row) if isinstance(row, (list, tuple)) else [row]
    check = seq[0] if len(seq) > 0 else ""
    result = seq[1] if len(seq) > 1 else ""
    ok = bool(seq[2]) if len(seq) > 2 else False
    return check, result, ok


def _crow(row):
    """Coerce a changes entry to a (file, purpose) pair so a malformed/short entry (e.g. a bare
    string or single-item tuple) renders instead of crashing the table."""
    seq = list(row) if isinstance(row, (list, tuple)) else [row]
    f = seq[0] if len(seq) > 0 else ""
    p = seq[1] if len(seq) > 1 else "—"
    return f, p


def _inline(x):
    """Flatten a value to a single inline string — collapse ALL whitespace (incl. newlines) so
    untrusted text (a task description) can't break the one-line banner or inject block markdown."""
    return " ".join(str(x).split())


def _fence(text):
    """Pick a backtick fence long enough to wrap `text` without its own backticks terminating the
    code block early — one longer than the longest backtick run inside (minimum 3)."""
    import re
    longest = max((len(m) for m in re.findall(r"`+", str(text))), default=0)
    return "`" * max(3, longest + 1)


def build_pr_body(*, summary, changes, verification, evidence=None, issue=None, codex=None, autonomous=True):
    """Render a professional PR body.

    summary      : one-line "what + why" (bolded banner).
    changes      : list of (file, purpose) tuples → the Changes table.
    verification : list of (check, result, ok: bool) tuples → the Verification table + the banner chips.
    evidence     : optional verbose text (test tail / receipt json) → collapsible <details>.
    issue        : optional int → "Closes #N".
    codex        : optional {"approved": bool, "verdict": str} → a Codex chip + verification row.
    autonomous   : adds the "never auto-merged — founder is the merge gate" note.
    """
    verification = [_vrow(r) for r in (verification or [])]
    if codex is not None:
        verification = verification + [("Codex review", codex.get("verdict", "review"), bool(codex.get("approved")))]
    all_ok = all(ok for _, _, ok in verification) if verification else False

    banner_chips = [chip(all_ok, "gate verified")]
    if codex is not None:
        banner_chips.append(chip(bool(codex.get("approved")), "Codex " + (codex.get("verdict") or "review")))
    if autonomous:
        banner_chips.append("🔒 founder-gated merge")

    parts = [f"> **{_inline(summary)}**", ">", "> " + " · ".join(banner_chips), ""]
    parts += ["## 📦 Changes",
              _table([(f"`{f}`", p) for f, p in (_crow(r) for r in (changes or []))] or [("—", "—")],
                     ["File", "Purpose"]), ""]
    parts += ["## ✅ Verification",
              _table([(c, ("✅ " if ok else "⚠️ ") + str(r)) for c, r, ok in verification] or [("—", "—")],
                     ["Check", "Result"]), ""]
    if evidence:
        ev = str(evidence).strip()[:3000]
        fence = _fence(ev)
        parts += ["<details>", "<summary>📋 Evidence</summary>", "", fence, ev, fence, "", "</details>", ""]
    foot = []
    if issue:
        foot.append(f"Closes #{int(issue)}")
    if autonomous:
        foot.append("never auto-merged — founder is the merge gate")
    foot.append(PROVENANCE)
    parts += ["---", " · ".join(foot)]
    return "\n".join(parts) + "\n"


_CONVENTIONAL_TYPES = ("feat", "fix", "docs", "test", "refactor", "perf", "chore", "build", "ci")


def build_commit(ctype, subject, *, scope=None, bullets=None, trailers=None):
    """Conventional-commits message: `type(scope): subject` + bullet body + trailers (e.g. Co-Authored-By)."""
    if ctype not in _CONVENTIONAL_TYPES:
        ctype = "chore"
    head = f"{ctype}({scope}): {subject}" if scope else f"{ctype}: {subject}"
    body = ("\n\n" + "\n".join(f"- {b}" for b in bullets)) if bullets else ""
    tr = ("\n\n" + "\n".join(trailers)) if trailers else ""
    return head + body + tr


def issue_ref(text):
    """Extract the first `#N` issue number from free text (e.g. a task description), or None."""
    import re
    m = re.search(r"#(\d{1,6})\b", text or "")
    return int(m.group(1)) if m else None


if __name__ == "__main__":
    print(build_pr_body(
        summary="demo: show the SEIF PR house style",
        changes=[("logos/pr_format.py", "the formatter"), ("tests/test_pr_format.py", "its tests")],
        verification=[("Tests (`unittest`)", "138 pass (exit 0)", True), ("Integrity guard", "clean", True)],
        evidence="Ran 138 tests in 0.7s\nOK",
        issue=25, codex={"approved": True, "verdict": "APPROVE"}))
