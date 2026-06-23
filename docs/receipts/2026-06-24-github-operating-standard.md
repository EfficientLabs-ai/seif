# Receipt — GitHub Operating Standard

**Date:** 2026-06-24
**Branch:** `chore/github-operating-standard`
**Author:** Neo The Architect · built by Claude (`agent:claude`), verified by Codex (`agent:codex`)

Proof that this PR is safe to merge, per the operating standard's own "Proof / Receipts" requirement.

## Tests / validation run

```
# Every YAML file parses (issue forms, CI gate, release notes, labels, config)
python -c "import yaml; ..."  →
OK   .github/workflows/pr-discipline.yml
OK   .github/workflows/seif-ci.yml        (untouched — existing CI preserved)
OK   .github/ISSUE_TEMPLATE/bug_report.yml
OK   .github/ISSUE_TEMPLATE/feature_request.yml
OK   .github/ISSUE_TEMPLATE/architecture_decision.yml
OK   .github/ISSUE_TEMPLATE/config.yml
OK   .github/release.yml
OK   .github/labels.yml
```

## Independent review (Codex)

> VERDICT: APPROVE — no required fixes identified.
> Reviewed `.github/workflows/pr-discipline.yml` (pull_request_target used safely — reads PR
> metadata only, no checkout/execution of PR code, minimal permissions, no script-injection
> vector), the three issue forms (valid GitHub issue-form schema), `release.yml`, `labels.yml`,
> `CODEOWNERS`, and the consolidated PR template.

## Live repo changes (outside the PR diff — repo metadata)

- **24 labels** created/updated via `gh label create` from `.github/labels.yml` (severity P0–P3,
  status, `impact:*`, `agent:*`, decision, `proof:*`). Repo now carries 34 labels total
  (10 existing defaults retained).

## Known limitations

- `pr-discipline.yml` enforces structure (sections, linked context, branch prefix, proof bullets),
  not semantic quality — a reviewer still judges substance.
- Issue templates are **forms (`.yml`)**, not plain `.md` (a deliberate upgrade for better UX).
- The two prior PR templates (`PULL_REQUEST_TEMPLATE.md` + lowercase `pull_request_template.md`)
  were consolidated into one canonical template; the lowercase duplicate was removed.
