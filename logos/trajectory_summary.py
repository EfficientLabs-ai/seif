#!/usr/bin/env python3
"""SEIF Structured Trajectory Summary (v0.2 WP-F) — the reusable unit for context + DOP, NOT raw
transcripts. After every attempt the loop emits a compact, typed record so future candidates get useful
EXPERIENCE (what was tried, what the evidence said, what's still open) without reloading apologies, dead
ends, and repeated code. Raw traces remain as evidence; summaries become context/skill candidates.
"""
import hashlib
import json

_FIELDS = ("attempt_id", "task_id", "hypothesis", "localization", "files_examined", "files_changed",
           "assumptions", "evidence_passed", "evidence_failed", "contradictions",
           "invalidated_assumptions", "unresolved_obligations", "cost", "latency_s",
           "termination_reason", "reusable_lesson_candidate", "prohibited_reuse_reasons")
_TERMINATIONS = {"accepted", "rejected", "insufficient_evidence", "budget_exhausted", "stuck",
                 "timeout", "error", "gate_complete"}


class SummaryError(ValueError):
    pass


def build_summary(attempt_id, task_id, hypothesis, termination_reason, *, localization="",
                  files_examined=None, files_changed=None, assumptions=None, evidence_passed=None,
                  evidence_failed=None, contradictions=None, invalidated_assumptions=None,
                  unresolved_obligations=None, cost=None, latency_s=None,
                  reusable_lesson_candidate="", prohibited_reuse_reasons=None):
    if termination_reason not in _TERMINATIONS:
        raise SummaryError(f"termination_reason must be one of {sorted(_TERMINATIONS)}")
    s = {
        "attempt_id": attempt_id, "task_id": task_id, "hypothesis": hypothesis,
        "localization": localization, "files_examined": list(files_examined or []),
        "files_changed": list(files_changed or []), "assumptions": list(assumptions or []),
        "evidence_passed": list(evidence_passed or []), "evidence_failed": list(evidence_failed or []),
        "contradictions": list(contradictions or []),
        "invalidated_assumptions": list(invalidated_assumptions or []),
        "unresolved_obligations": list(unresolved_obligations or []),
        "cost": cost or {}, "latency_s": latency_s, "termination_reason": termination_reason,
        "reusable_lesson_candidate": reusable_lesson_candidate,
        "prohibited_reuse_reasons": list(prohibited_reuse_reasons or []),
    }
    validate(s)
    return s


def validate(s):
    missing = [f for f in _FIELDS if f not in s]
    if missing:
        raise SummaryError(f"summary missing {missing}")
    if not s["attempt_id"] or not s["task_id"] or not s["hypothesis"]:
        raise SummaryError("attempt_id/task_id/hypothesis required")
    if s["termination_reason"] not in _TERMINATIONS:
        raise SummaryError(f"bad termination_reason {s['termination_reason']}")
    try:
        json.dumps(s)
    except TypeError as e:
        raise SummaryError(f"summary must be plain JSON: {e}")
    return True


def is_reusable(s):
    """A summary is a reuse/skill candidate only if it ACCEPTED with a lesson and NO prohibition. DOP
    still gates promotion (shadow -> held-out -> human); this is just the cheap first filter."""
    return (s["termination_reason"] in ("accepted", "gate_complete")
            and bool(s["reusable_lesson_candidate"]) and not s["prohibited_reuse_reasons"])


def fingerprint(s):
    return hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()[:16]


def _selftest():
    s = build_summary("att1", "task_demo", "cache-key identity bug", "gate_complete",
                      localization="src/cache.py", files_changed=["src/cache.py"],
                      evidence_passed=["L2", "L3"], unresolved_obligations=[],
                      reusable_lesson_candidate="resolve paths before keying the conftest cache",
                      cost={"usd": 0.0, "turns": 2}, latency_s=41.0)
    assert validate(s) and is_reusable(s), "accepted+lesson+no-prohibition => reusable candidate"
    # a rejected attempt with an open obligation is NOT reusable, but is still a valid summary
    f = build_summary("att2", "task_demo", "narrow fix", "rejected",
                      evidence_failed=["L2"], unresolved_obligations=["O3"],
                      prohibited_reuse_reasons=["overfit to visible test"])
    assert validate(f) and not is_reusable(f)
    # bad termination rejected
    try:
        build_summary("a", "t", "h", "looks-good"); raise AssertionError("bad termination accepted")
    except SummaryError:
        pass
    assert fingerprint(s) != fingerprint(f)
    print("trajectory_summary selftest PASS — typed summary, reuse-candidate filter, plain-JSON, fingerprint")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: trajectory_summary.py --selftest")
