# docs/screenshots/ — Visual Receipts

This folder holds **visual proof** for pull requests: before/after comparisons, UI proof, terminal screenshots, and any image that demonstrates a change works.

It is the visual counterpart to [`docs/receipts/`](../receipts/), which holds text/log receipts. Together they back the **Proof / Receipts** section every PR must include.

## Naming convention

```
<YYYY-MM-DD>-<pr-or-issue>-<short>.png
```

- `<YYYY-MM-DD>` — date the screenshot was captured.
- `<pr-or-issue>` — the PR or issue number, e.g. `pr-42` or `issue-17`.
- `<short>` — a short kebab-case description.

Examples:

```
2026-06-24-pr-42-before.png
2026-06-24-pr-42-after.png
2026-06-24-issue-17-cli-output.png
```

## Usage

Reference screenshots from a PR's **Proof / Receipts** section:

```markdown
- Screenshots / CLI output: docs/screenshots/2026-06-24-pr-42-after.png
- Before / after: docs/screenshots/2026-06-24-pr-42-before.png → docs/screenshots/2026-06-24-pr-42-after.png
```

Apply the `proof:screenshot` label when a PR's proof is primarily visual.

Keep it clean: one clear image per claim, named consistently, linked from the PR.
