<!-- SEIF house style banner (existing, KEEP) -->
> **<one-line: what + why>**
>
> ✅ gate verified · 🔒 founder-gated merge

<!--
EFFICIENT LABS — PR template (OpenClaw standard).
Every PR MUST keep the H1 sections below, in order. Fill each one; do not delete headings.
A PR is NOT done until: it explains the problem, explains the solution, states user/project
impact, links context, includes proof, CI passes, review is complete, and main stays protected.
Branch flow: main → <prefix>/<short-kebab-name> → draft PR → CI + proof → review → ready → squash merge.
Title: use a Conventional Commit subject — type(optional-scope): subject (imperative, lowercase, no period).
-->

# Summary
<!-- Plain-English: what changed. One or two sentences. -->

# Problem
<!-- What was broken / missing / unclear / risky / incomplete. -->

# Solution
<!-- How this PR solves it. -->

# User / Project Impact
<!-- Who benefits, what improves. -->

# Linked Context
<!-- Related issue / ADR / commit / doc / product decision. Use "Closes #N". -->
Closes #<issue>

# Proof / Receipts
<!-- Receipts live in docs/receipts/ (logs) and docs/screenshots/ (visual). Attach them. -->
- Tests run:
- Logs checked:
- Screenshots / CLI output:
- Before / after:
- Edge cases tested:
- Known limitations:

# Merge Readiness
<!-- All boxes must be checked before this PR can be merged. -->
- [ ] Branch created from latest main
- [ ] No direct commits to main
- [ ] CI passing
- [ ] Kernel selftest green (CI)
- [ ] Schemas valid (CI)
- [ ] ADR added/updated if architectural
- [ ] Review completed
- [ ] Comments resolved
- [ ] Proof attached
- [ ] Squash merge only

<!--
Founder gate: this PR is never auto-merged. The founder (@Neo-The-Architect) is the merge gate.
main is protected — squash-merge only, never direct-commit.
-->
