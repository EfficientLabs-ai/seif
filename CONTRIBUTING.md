# Contributing to Efficient Labs

Repository: `EfficientLabs-ai/seif` · Maintainer: @Neo-The-Architect

This repo runs like an operating system: clean PR and issue titles, consistent labels, linked issues and docs, visible proof before merge, a reviewer checklist, and no chaotic commits on `main`. This guide is the contract. Read it before opening your first PR.

---

## Branch flow

`main` is protected. Never commit to it directly. All work happens on a branch and lands via squash merge.

```
main → <prefix>/<short-kebab-name> → draft PR → CI + proof → review → ready for review → squash merge to main
```

### Allowed branch prefixes

Use exactly one of these prefixes, followed by a short kebab-case name:

| Prefix | Use for |
|---|---|
| `feat/` | New functionality |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `chore/` | Maintenance, deps, tooling |
| `refactor/` | Behavior-preserving restructuring |
| `test/` | Tests only |
| `ci/` | CI / pipeline configuration |
| `security/` | Security fixes and hardening |
| `release/` | Release preparation |

Examples: `feat/event-log-replay`, `fix/fsm-transition-guard`, `docs/contributing-guide`.

---

## Conventional Commits

Every commit message follows Conventional Commits:

```
type(optional-scope): subject
```

- **Subject:** imperative mood, lowercase, no trailing period.
- **Body:** bullet points are encouraged for the what/why.
- **Trailers:** `Co-Authored-By:` is allowed and encouraged for multi-agent work.

### Allowed types (exact)

`feat` `fix` `docs` `chore` `refactor` `test` `ci` `security` `perf` `build`

### Examples per type

```
feat(replay): add deterministic event-log replay
fix(fsm): reject illegal state transition on guard failure
docs: document the PR body standard
chore(deps): bump policy-gate to 1.4.0
refactor(graph): extract hybrid query into its own module
test(policy): cover deny-by-default edge cases
ci: run integrity guard on every pull request
security: redact secrets from tool output paths
perf(vector): cache embeddings for repeated lookups
build: pin node abi for native modules
```

---

## Pull request body standard

Every PR body MUST use these H1 sections, in this exact order. This is the "OpenClaw" standard and it is enforced by the PR template (`.github/PULL_REQUEST_TEMPLATE.md`).

```markdown
# Summary
Plain-English what changed.

# Problem
What was broken / missing / unclear / risky / incomplete.

# Solution
How this PR solves it.

# User / Project Impact
Who benefits, what improves.

# Linked Context
Related issue / ADR / commit / doc / product decision. Use "Closes #N".

# Proof / Receipts
- Tests run:
- Logs checked:
- Screenshots / CLI output:
- Before / after:
- Edge cases tested:
- Known limitations:

# Merge Readiness
- [ ] Branch created from latest main
- [ ] No direct commits to main
- [ ] CI passing
- [ ] Review completed
- [ ] Comments resolved
- [ ] Proof attached
- [ ] Squash merge only
```

---

## Definition of Done

A PR is **not done** until:

1. It explains the problem.
2. It explains the solution.
3. It states user/project impact.
4. It links context.
5. It includes proof.
6. CI passes.
7. Review is complete.
8. `main` stays protected.

---

## Reviewer comment template

Reviewers leave one structured comment. Copy this verbatim:

```markdown
## Review Result
Status: Approved / Changes Requested / Comment Only

## What I Checked
- Code correctness:
- Security:
- Tests:
- Docs:
- User impact:
- Regression risk:

## Required Changes
List required changes, or write "None."

## Verification
Explain what proof confirms this PR is safe to merge.
```

---

## Labels

Labels are managed in `.github/labels.yml`. Existing default labels (`bug`, `enhancement`, `documentation`, `question`, etc.) are kept, not removed.

| Group | Labels |
|---|---|
| **severity** | `P0` (critical/now), `P1` (high), `P2` (medium), `P3` (low) |
| **status** | `needs-proof` (proof/receipts missing), `needs-review` (awaiting review), `blocked` (blocked on a dependency), `ready-to-merge` (approved + proven) |
| **impact** | `impact:user`, `impact:security`, `impact:infra`, `impact:docs`, `impact:revenue` |
| **agent** | `agent:claude`, `agent:codex`, `agent:gemini`, `agent:neo` |
| **decision** | `product-decision`, `architecture-decision`, `governance-decision` |
| **proof** | `proof:tests`, `proof:logs`, `proof:screenshot`, `proof:manual-verification` |

---

## Attaching proof

Proof is mandatory before merge. No PR merges without receipts.

- **Logs and CLI output** → `docs/receipts/`
- **Screenshots and visual evidence** → `docs/screenshots/`
- **Architecture decisions** → `docs/adr/`

Reference the proof files from the `# Proof / Receipts` section of your PR body so reviewers can find them. A PR that claims "tests pass" without a checked-in receipt is missing proof; apply `needs-proof` until it is attached.

---

## Merge policy

- **Squash merge only.** Every PR collapses to a single clean commit on `main`.
- **`main` is protected.** No direct commits, no force-pushes. Branch, PR, review, then squash.
- A PR merges only when CI is green, review is complete, comments are resolved, and proof is attached.

---

## Tri-model review

Substantive code changes run through the tri-model team before they are considered done:

**Claude builds → Codex verifies → Gemini tie-breaks.**

Claude authors the change, Codex reviews it for correctness and risk, and Gemini breaks any tie when the first two disagree. Record which agents were involved with the corresponding `agent:*` labels and credit them via `Co-Authored-By:` trailers.
