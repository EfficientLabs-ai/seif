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
Both arms share `swe_common.prepare_clone` so they operate on **byte-identical** clones; the only
intended difference is Arm B's execution-feedback loop.
- **Arm A (baseline)** — `swe_arm_a.py`: clone repo@base_commit → `claude -p --permission-mode acceptEdits` (edits from reasoning, no headless test execution = **blind-patch** baseline) → `git diff` = model_patch → scored by the harness.
- **Arm B (LOGOS)** — `swe_arm_b.py` (BUILT 2026-06-21): same clone, plus a real execution-feedback loop. The agent writes a self-authored reproduction `logos_repro.py`; the harness runs it in the per-instance swebench testbed image (`arm_b_testbed.py`: deps installed, `--network=none`, ephemeral) and feeds the result back for up to 3 turns. A passing repro only counts with a **non-empty source fix**. Held-out grading tests (`test_patch`) never touch the testbed → **no oracle leak**. Final source-only patch (repro excluded via pathspec, test edits filtered) scored by the SAME harness. Lifecycle ledgered through the SEIF kernel. Codex-reviewed (REQUEST_CHANGES → all HIGH/MED fixed).

### Image naming (Docker Hub)
Prebuilt instance images live at `swebench/sweb.eval.x86_64.<iid>` with `__` normalized to `_1776_`
(e.g. `psf__requests-2931` → `swebench/sweb.eval.x86_64.psf_1776_requests-2931:latest`). `arm_b_testbed.ensure_image` pulls these; Arm-B's batch thus warms the cache the scorer reuses.

### Runners + analysis
- `curate.py` → `eval_set_20.json` (adaptive stratified 20: fills scarce multi/large buckets fully).
- `run_batch.py` (Arm A) / `run_batch_b.py` (Arm B): resumable — skip any instance whose preds exist.
- `analyze.py [--score]`: scores both arms via the official harness, then per-arm resolve rate +
  Wilson 95% CI, the per-bucket **degradation curve**, and an exact McNemar paired test → `logs/AB_REPORT.md`.

### First head-to-head (1 instance, 2026-06-21)
`psf__requests-2931`: Arm A **unresolved**, Arm B **unresolved** (~19s/score, cached image). Both produced
the same `_encode_params` change; Arm B's feedback did NOT rescue it because the agent's self-authored
repro PASSED with a wrong fix — a weak repro yields a false-positive feedback signal. Honest finding,
not a harness fault: execution feedback is only as strong as the reproduction. Full 20×arm A/B delta pending.

Protocol target: 20 tasks stratified by gold-file count, ≥3 seeds/arm, p<0.05, 95% CIs, the success-vs-task-length **degradation curve** as the headline. See `eval/EVALUATION.md` + `eval/LOGOS_EXECUTION_PLAN.md`.
