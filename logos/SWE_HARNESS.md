# SWE-bench-Verified harness (Phase 2)

The **official `swebench` harness is the scorer** — we do NOT re-implement FAIL_TO_PASS/PASS_TO_PASS. It runs each instance's held-out grading tests in the per-instance Docker env. This keeps every number honest and reproducible.

- **venv:** `/home/neo/logos-venv` (swebench 4.1.0, datasets 5.0.0). Run scoring with `/home/neo/logos-venv/bin/python`.
- **Dataset:** `princeton-nlp/SWE-bench_Verified` (500 instances). Light repos for iteration: `psf/requests` (8), `pytest-dev/pytest` (19). Heavy: `django/django` (231).

## PROVEN (2026-06-20)
Gold-patch sanity on `psf__requests-2931` → **resolved: 1** in 81s (image pulled from `swebench` namespace, gold patch applied, held-out tests run + scored). The measurement infra is correct.

```
# score gold patches (sanity):
python -m swebench.harness.run_evaluation -d princeton-nlp/SWE-bench_Verified -s test \
  -i <instance_id> -p gold -id sanity_gold -n swebench --max_workers 1

# score a model's predictions jsonl ({instance_id, model_name_or_path, model_patch}):
python -m swebench.harness.run_evaluation -d princeton-nlp/SWE-bench_Verified -s test \
  -p <predictions.jsonl> -id <run_id> -n swebench --max_workers <N>
```

## Arms (honest A/B)
- **Arm A (baseline)** — `swe_arm_a.py`: clone repo@base_commit → `claude -p --permission-mode acceptEdits` (edits from reasoning, no headless test execution = **blind-patch** baseline) → `git diff` = model_patch → scored by the harness.
- **Arm B (LOGOS)** — *next*: the same model + the LOGOS execution plane (sandboxed execution-feedback, FSM/ledger, independent verify, best-of-3). The A/B **delta** isolates that mechanism; same model/config both arms keeps it fair.

Protocol: 20 tasks stratified (5 single-file / 5 multi-same / 5 multi-cross / 5 refactor), ≥3 seeds/arm, p<0.05, 95% CIs, the success-vs-task-length **degradation curve** as the headline. See `eval/EVALUATION.md` + `eval/LOGOS_EXECUTION_PLAN.md`.
