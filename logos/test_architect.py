#!/usr/bin/env python3
"""SEIF Candidate-Blind Test Architect (v0.2 WP-B) — an INDEPENDENT author of acceptance evidence that
breaks the confirmation-bias loop measured in Findings 001-004 (the agent that writes the fix must not
also write the exam).

It MAY see: the issue, the UNMODIFIED base repo, architecture, public tests, and the Evidence Contract.
It MUST NOT see: the candidate patch, implementer reasoning, the candidate's self-authored reproduction,
the hidden SWE-bench grading tests (test_patch / FAIL_TO_PASS / PASS_TO_PASS), or the reference/gold patch.

Blindness is ENFORCED structurally: `build_context` only assembles an allowlist of fields, and
`assert_blind` raises on any forbidden key anywhere in the context — so candidate/gold/hidden material
cannot enter the Test Architect's input. The generated plan is FROZEN + hashed (recorded in the receipt);
the implementer can't modify it. LLM generation is an INJECTED `generator(context)` (a real model in
production; a stub in tests) so the blindness machinery is verifiable without a live model.
"""
import hashlib
import json

ALLOWED_CONTEXT_KEYS = {"task_id", "issue", "repo_view", "public_tests", "architecture", "contract"}
FORBIDDEN_KEYS = {
    "candidate", "candidate_patch", "patch", "model_patch", "diff",
    "gold", "gold_patch", "reference_patch", "solution",
    "hidden_tests", "grading_tests", "test_patch", "fail_to_pass", "pass_to_pass",
    "reproduction", "repro", "logos_repro", "implementer_reasoning",
}
TEST_KINDS = {"acceptance", "negative", "edge", "property", "metamorphic", "regression_hypothesis"}


class BlindnessError(ValueError):
    pass


class PlanError(ValueError):
    pass


def build_context(task_id, issue, *, repo_view=None, public_tests=None, architecture=None, contract=None):
    """Assemble ONLY the allowlisted, blind context. `repo_view`/`public_tests` must be base-repo material
    (no candidate). Raises if any input smuggles forbidden content."""
    ctx = {"task_id": task_id, "issue": issue, "repo_view": repo_view or [],
           "public_tests": public_tests or [], "architecture": architecture or ""}
    if contract is not None:
        ctx["contract"] = contract
    assert_blind(ctx)
    return ctx


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_keys(v)


def assert_blind(context):
    """Structurally enforce blindness. (1) top-level keys ⊆ allowlist; (2) NO forbidden key anywhere in
    the (nested) context — except inside the Evidence Contract, which legitimately names protected paths
    like 'test_patch'. Raises BlindnessError on any violation."""
    extra = set(context.keys()) - ALLOWED_CONTEXT_KEYS
    if extra:
        raise BlindnessError(f"non-allowlisted context keys: {sorted(extra)}")
    scan = {k: v for k, v in context.items() if k != "contract"}   # contract may reference protected names
    for key in _walk_keys(scan):
        if key.lower() in FORBIDDEN_KEYS:
            raise BlindnessError(f"forbidden key in Test Architect context: {key!r} (candidate/gold/hidden material)")
    return True


def _canonical(plan):
    return json.dumps({k: v for k, v in plan.items() if k != "plan_hash"}, sort_keys=True, separators=(",", ":"))


def freeze_plan(plan):
    """Validate + stamp a content hash. Frozen before any candidate is shown; recorded in the receipt."""
    if not isinstance(plan.get("tests"), list) or not plan["tests"]:
        raise PlanError("plan must have a non-empty 'tests' list")
    for t in plan["tests"]:
        if not isinstance(t, dict) or "id" not in t or t.get("kind") not in TEST_KINDS:
            raise PlanError(f"each test needs id + kind in {sorted(TEST_KINDS)}: {t!r}")
    p = {**plan, "plan_hash": ""}
    p["plan_hash"] = hashlib.sha256(_canonical(p).encode()).hexdigest()[:16]
    return p


def verify_plan_unmutated(plan):
    h = plan.get("plan_hash")
    return bool(h) and h == hashlib.sha256(_canonical(plan).encode()).hexdigest()[:16]


def author_tests(context, generator):
    """Run the candidate-blind generator over the verified-blind context and freeze the result.
    `generator(context)->{tests:[{id,kind,...}], ...}` is the LLM in production. Blindness is asserted
    BEFORE the generator ever sees the context, so a candidate can never leak into test authoring."""
    assert_blind(context)                       # gate the input before the model sees it
    plan = generator(context) or {}
    if not isinstance(plan, dict):
        raise PlanError("generator must return a dict plan")
    return freeze_plan(plan)


def _selftest():
    import evidence_contract as EC
    o = EC.make_obligation("O1", "x", "issue", "e", ["candidate_blind_test"], "r", "u")
    contract = EC.build_contract("t", "fix bug", [o])           # contract legitimately names test_patch etc.
    ctx = build_context("t", "Issue: binary body mishandled", repo_view=["src/models.py"],
                        public_tests=["tests/test_models.py"], architecture="layered", contract=contract)
    assert assert_blind(ctx)

    # blindness: candidate/gold/hidden material cannot enter
    for bad in ({"task_id": "t", "issue": "i", "candidate_patch": "diff..."},
                {"task_id": "t", "issue": "i", "gold": "the answer"},
                {"task_id": "t", "issue": "i", "repo_view": [{"test_patch": "hidden"}]},
                {"task_id": "t", "issue": "i", "extra_field": 1}):
        try:
            assert_blind(bad); raise AssertionError(f"blindness must reject {list(bad)}")
        except BlindnessError:
            pass

    # a stub generator only ever receives the blind context; plan is frozen + tamper-evident
    seen = {}
    def gen(c):
        seen.update(c)
        return {"tests": [{"id": "T1", "kind": "acceptance", "intent": "bytes stay bytes"},
                          {"id": "T2", "kind": "negative", "intent": "text unaffected"},
                          {"id": "T3", "kind": "property", "intent": "roundtrip"}]}
    plan = author_tests(ctx, gen)
    assert "candidate_patch" not in seen and "gold" not in seen, "generator saw only blind context"
    assert verify_plan_unmutated(plan) and plan["plan_hash"], "plan frozen + hashed"
    plan["tests"][0]["intent"] = "weakened"
    assert not verify_plan_unmutated(plan), "implementer cannot modify the frozen plan undetected"
    # bad plan rejected
    try:
        freeze_plan({"tests": [{"id": "x", "kind": "not_a_kind"}]}); raise AssertionError("bad kind accepted")
    except PlanError:
        pass
    print("test_architect selftest PASS — blindness structurally enforced (candidate/gold/hidden rejected); "
          "generator sees only blind context; plan frozen + tamper-evident")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: test_architect.py --selftest")
