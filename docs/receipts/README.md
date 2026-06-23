# docs/receipts/ — Proof Logs

This folder holds **proof logs**: the textual evidence attached to pull requests in the `EfficientLabs-ai/seif` repo. A PR is not done until proof is attached (see the Definition of Done in the GitHub Operating Standard).

Visual proof (screenshots) lives in [`docs/screenshots/`](../screenshots/). Architecture decisions live in [`docs/adr/`](../adr/).

## What belongs here

- Test output (unit, integration, e2e runs)
- CLI runs and command output
- Hash-chained SEIF receipts
- Codex review verdicts and verification logs

## Naming convention

```
<YYYY-MM-DD>-<pr-or-issue>-<short>.md
<YYYY-MM-DD>-<pr-or-issue>-<short>.log
```

- `<YYYY-MM-DD>` — date the proof was captured
- `<pr-or-issue>` — `pr-123` or `issue-45`
- `<short>` — short kebab-case description

Examples:

```
2026-06-24-pr-123-test-run.log
2026-06-24-pr-123-codex-verdict.md
2026-06-24-issue-45-seif-receipt.md
```

## How these are referenced

Every PR carries a `# Proof / Receipts` section. Link the files here from that section so reviewers can trace each claim to its evidence:

```
# Proof / Receipts
- Tests run: docs/receipts/2026-06-24-pr-123-test-run.log
- Logs checked: docs/receipts/2026-06-24-pr-123-codex-verdict.md
```

Use the `proof:tests`, `proof:logs`, and `proof:manual-verification` labels on the PR to flag which kinds of receipts are attached.
