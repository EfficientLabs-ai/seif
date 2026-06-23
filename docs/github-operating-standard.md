# Efficient Labs — GitHub Operating Standard

> The master reference. Every other governance file in this repo — `CONTRIBUTING.md`, `.github/labels.yml`, the PR template, the issue forms, CODEOWNERS, and the CI workflows — implements a slice of this document. When they disagree, this document is canonical.

- **Repository:** `EfficientLabs-ai/seif`
- **Owner / maintainer:** @Neo-The-Architect
- **Default branch:** `main` — protected, never direct-committed, squash-merge only.

---

## 1. Philosophy — the repo as an operating system

A repository is not a dumping ground for code. It is the operating system the team runs on. An OS has process isolation, a scheduler, permissions, and an audit log. So does a healthy repo:

- **Process isolation** → every change lives on its own branch, never on `main`.
- **The scheduler** → the project board moves work through fixed, visible states.
- **Permissions** → branch protection, CODEOWNERS, and the founder merge gate.
- **The audit log** → linked issues, ADRs, and checked-in proof, so any decision can be traced after the fact.

What this feels like in practice:

- Clean, conventional PR and issue titles — readable at a glance, six months later.
- Consistent labels — the board state is legible without opening a single PR.
- Every change linked to its issue, ADR, or product decision.
- Visible proof before merge — receipts, logs, screenshots, never "trust me."
- A reviewer checklist that is the same every time.
- No chaotic commits on `main`. Ever.

If a contribution makes the repo harder to reason about, it is not done, regardless of whether the code works.

---

## 2. The full lifecycle

Every unit of work flows through the same pipeline. No step is optional.

```
issue (form) → branch → draft PR → CI + proof → review → ready for review → squash merge to main
```

| # | Stage | What happens | Board column |
|---|---|---|---|
| 1 | **Issue** | Work is filed via an issue form (feature request, architecture decision, bug). It gets `severity`, `impact`, and `agent` labels. | Backlog → Ready |
| 2 | **Branch** | A branch is cut from the latest `main` using an allowed prefix and a short kebab name. | In Progress |
| 3 | **Draft PR** | A draft PR opens early, using the PR body standard. It links the issue with `Closes #N`. | In Progress |
| 4 | **CI + proof** | CI runs; the author attaches receipts to `docs/receipts/` and screenshots to `docs/screenshots/`. Until proof is attached, the PR carries `needs-proof`. | Needs Proof |
| 5 | **Review** | A reviewer posts the canonical reviewer comment. The PR carries `needs-review` until a verdict lands. | In Review |
| 6 | **Ready for review** | Draft flips to "ready for review." All comments are resolved; `ready-to-merge` is applied. | Ready to Merge |
| 7 | **Squash merge** | The founder squash-merges to `main`. One clean commit. The issue auto-closes. | Done |

### 2.1 Branch flow and prefixes

`main` is protected. Never commit to it directly. All work happens on a branch and lands via squash merge.

```
main → <prefix>/<short-kebab-name> → draft PR → CI + proof → review → ready for review → squash merge to main
```

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

Examples: `feat/event-log-replay`, `fix/fsm-transition-guard`, `docs/github-operating-standard`.

### 2.2 Conventional Commits

Every commit message follows Conventional Commits:

```
type(optional-scope): subject
```

- **Subject:** imperative mood, lowercase, no trailing period.
- **Body:** bullet points encouraged for the what/why.
- **Trailers:** `Co-Authored-By:` is allowed and encouraged for multi-agent work.

Allowed types (exact): `feat` `fix` `docs` `chore` `refactor` `test` `ci` `security` `perf` `build`

### 2.3 The PR body standard ("OpenClaw")

Every PR body MUST use these H1 sections, in this exact order. It is enforced by the PR template (`.github/pull_request_template.md`).

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

### 2.4 Reviewer comment template

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

### 2.5 Tri-model review

Substantive code changes run through the tri-model team before they are considered done:

**Claude builds → Codex verifies → Gemini tie-breaks.**

Claude authors the change, Codex reviews it for correctness and risk, and Gemini breaks any tie when the first two disagree. Record which agents were involved with the corresponding `agent:*` labels and credit them via `Co-Authored-By:` trailers.

---

## 3. Label taxonomy

Labels are the OS's status registers. They are managed in `.github/labels.yml` and referenced throughout the docs. Existing default labels (`bug`, `enhancement`, `documentation`, `question`, etc.) are kept, not removed.

### Severity — how urgent

| Label | Color | Description |
|---|---|---|
| `P0` | `#b60205` | critical/now |
| `P1` | `#d93f0b` | high |
| `P2` | `#fbca04` | medium |
| `P3` | `#0e8a16` | low |

### Status — where it is in the pipeline

| Label | Color | Description |
|---|---|---|
| `needs-proof` | `#d4c5f9` | proof/receipts missing |
| `needs-review` | `#fef2c0` | awaiting review |
| `blocked` | `#000000` | blocked on a dependency |
| `ready-to-merge` | `#0e8a16` | approved + proven |

### Impact — who it touches

| Label | Color | Description |
|---|---|---|
| `impact:user` | `#1d76db` | affects end users |
| `impact:security` | `#b60205` | affects security posture |
| `impact:infra` | `#5319e7` | affects infrastructure |
| `impact:docs` | `#0075ca` | affects documentation |
| `impact:revenue` | `#0e8a16` | affects revenue |

### Agent — who worked it

| Label | Color | Description |
|---|---|---|
| `agent:claude` | `#6f42c1` | Claude (builder) |
| `agent:codex` | `#24292e` | Codex (reviewer) |
| `agent:gemini` | `#1a73e8` | Gemini (tie-breaker) |
| `agent:neo` | `#d4af37` | Neo (founder) |

### Decision — what kind of decision it records

| Label | Color | Description |
|---|---|---|
| `product-decision` | `#c2e0c6` | product decision |
| `architecture-decision` | `#5319e7` | architecture decision |
| `governance-decision` | `#b60205` | governance decision |

### Proof — what evidence is attached

| Label | Color | Description |
|---|---|---|
| `proof:tests` | `#0e8a16` | test output attached |
| `proof:logs` | `#fbca04` | logs attached |
| `proof:screenshot` | `#1d76db` | screenshot attached |
| `proof:manual-verification` | `#d93f0b` | manually verified |

---

## 4. Milestone naming system

Milestones group issues and PRs into shippable or time-boxed units. Use one of two naming schemes, consistently:

- **Version milestones** — `vX.Y` for product releases. Example: `v0.2`, `v1.0`. Bump the minor for feature drops, the major for breaking or landmark releases.
- **Theme milestones** — `YYYY-Qn-theme` for time-boxed quarterly themes. Example: `2026-Q3-hardening`, `2026-Q4-launch`.

Rules:

- A milestone has a one-line description stating what "done" means and a due date.
- Every non-trivial issue is assigned to exactly one milestone.
- Version and theme milestones may coexist (a `v0.2` release can be worked inside a `2026-Q3-hardening` theme).
- Close a milestone only when every issue inside it is closed or explicitly punted to a named successor milestone.

---

## 5. Project board

The board is the scheduler. Columns are states; cards move left to right and never skip. The columns map one-to-one to the lifecycle.

| Column | A card lives here when… | Exit condition |
|---|---|---|
| **Backlog** | Filed but not yet scheduled. | Triaged, labeled, milestoned. |
| **Ready** | Triaged and ready to pick up. | A branch is cut. |
| **In Progress** | A branch and (draft) PR exist; work is active. | Code complete, CI invoked. |
| **In Review** | A reviewer is working through the reviewer template. | A review verdict is posted. |
| **Needs Proof** | Approved in principle, but receipts/screenshots are missing. | Proof checked in and referenced; `needs-proof` removed. |
| **Ready to Merge** | CI green, review complete, comments resolved, proof attached, `ready-to-merge` applied. | Founder squash-merges. |
| **Done** | Squash-merged to `main`; issue auto-closed. | — |

A card that is `blocked` keeps its column and carries the `blocked` label until the dependency clears.

---

## 6. CODEOWNERS

`CODEOWNERS` (`.github/CODEOWNERS`) encodes the permissions layer of the OS. Its purpose:

- **Automatic review requests.** Touch a path, and its owner is auto-requested as a reviewer.
- **Merge authority.** Combined with branch protection, it ensures the founder (@Neo-The-Architect) is required to approve changes to protected paths.
- **Sensitive-zone gating.** Governance, kernel, and schema directories carry explicit ownership so no agent or contributor can quietly alter the rules of the system.

Current ownership: the founder owns everything (`*`) and is named explicitly on `/governance/`, `/kernel/`, and `/schemas/`. Agent machine-user identities are added to CODEOWNERS once provisioned, never before.

---

## 7. Release notes and changelog policy

- **`CHANGELOG.md`** lives at the repo root and follows the *Keep a Changelog* shape: an `## [Unreleased]` section at the top, then one section per released version in reverse-chronological order, grouped under `Added`, `Changed`, `Fixed`, `Security`, `Removed`.
- Each merged PR adds a one-line entry to `## [Unreleased]`. The Conventional Commit type drives the group (`feat` → Added, `fix` → Fixed, `security` → Security, etc.).
- **Versions are SemVer** and match the `vX.Y` milestone that shipped them.
- **Cutting a release:** rename `## [Unreleased]` to the version and date, open a fresh empty `## [Unreleased]`, tag the squash commit `vX.Y.Z`, and publish a GitHub Release whose notes are that changelog section. Release branches use the `release/` prefix.
- A release note states what changed, who it affects (mirroring the `impact:*` labels), and links to the relevant ADRs.

---

## 8. ADR policy

Architecture Decision Records capture *why*, so future contributors do not relitigate settled questions.

- ADRs live in **`docs/adr/`**, named `NNNN-short-kebab-title.md` with a zero-padded, monotonically increasing number (e.g. `0001-event-log-as-source-of-truth.md`).
- Each ADR has: **Status** (Proposed / Accepted / Superseded by NNNN), **Context**, **Decision**, **Consequences**.
- An architecture or governance decision is filed through the architecture-decision issue form, labeled `architecture-decision` (or `governance-decision`), and lands as an ADR file in the same PR that implements it.
- ADRs are immutable once Accepted. To change a decision, write a new ADR that supersedes the old one and update the old one's Status line — never edit history.
- PRs that make a structural choice link the ADR in their `# Linked Context` section.

---

## 9. Receipts and screenshots

Proof is mandatory before merge. No PR merges without receipts.

- **Logs and CLI output** → `docs/receipts/`
- **Screenshots and visual evidence** → `docs/screenshots/`
- **Architecture decisions** → `docs/adr/`

Reference the proof files from the `# Proof / Receipts` section of your PR body so reviewers can find them. A PR that claims "tests pass" without a checked-in receipt is missing proof; apply `needs-proof` until it is attached. Name proof files after the PR or issue they back (e.g. `docs/receipts/pr-42-test-run.txt`) so the audit trail stays legible.

---

## 10. Definition of Done

A PR is **not done** until:

1. It explains the problem.
2. It explains the solution.
3. It states user/project impact.
4. It links context.
5. It includes proof.
6. CI passes.
7. Review is complete.
8. `main` stays protected.

All eight must hold. Code that runs but fails any of these is not done.

---

## 11. How to copy this standard to another repo

This document is the canonical standard other Efficient Labs repos copy. To adopt it:

- [ ] Copy `docs/github-operating-standard.md` (this file) and `CONTRIBUTING.md` into the new repo.
- [ ] Copy `.github/labels.yml` and apply it (it carries the full label taxonomy in §3, with default labels kept).
- [ ] Copy `.github/pull_request_template.md` (the OpenClaw PR body standard from §2.3).
- [ ] Copy the issue forms in `.github/ISSUE_TEMPLATE/` (feature request, architecture decision, bug).
- [ ] Copy `.github/CODEOWNERS` and update the path-to-owner map for the new repo's layout (§6).
- [ ] Copy the CI workflows in `.github/workflows/` (PR discipline + the repo's real test suite).
- [ ] Create the proof folders: `docs/receipts/`, `docs/screenshots/`, and `docs/adr/` (§8, §9).
- [ ] Set the default branch to `main` and enable branch protection: require PRs, require CI, require review, **squash-merge only**, no direct commits, no force-push.
- [ ] Create the project board with the seven columns in §5 (Backlog → Ready → In Progress → In Review → Needs Proof → Ready to Merge → Done).
- [ ] Define the first milestone using the §4 naming system (`vX.Y` or `YYYY-Qn-theme`).
- [ ] Seed `CHANGELOG.md` with an empty `## [Unreleased]` section (§7).
- [ ] Update the repo/owner references at the top of each copied file to the new repo's name and maintainer.

Once these are in place, the new repo runs the same operating system — and a contributor who knows one repo knows them all.
