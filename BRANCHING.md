# Branching Standard

**Repo:** `EfficientLabs-ai/seif` · **Owner:** @Neo-The-Architect · **Default branch:** `main`

`main` is protected. No one — human or agent — commits to it directly. All change flows through a branch and a squash-merged PR. The repo should feel like an operating system: clean titles, consistent labels, linked context, visible proof before merge, no chaotic main-branch commits.

---

## The Flow

```
                    ┌──────────────────────────────────────────────┐
                    │                  main (protected)            │
                    └───────────────────────┬──────────────────────┘
                                            │ branch from latest main
                                            ▼
                          <prefix>/<short-kebab-name>
                                            │ open as
                                            ▼
                                       draft PR
                                            │
                                            ▼
                                   CI + proof attached
                                            │
                                            ▼
                                        review
                                            │ approved + comments resolved
                                            ▼
                                   ready for review
                                            │
                                            ▼
                          squash merge ──────────────► main
```

`main` → `<prefix>/<short-kebab-name>` → draft PR → CI + proof → review → ready for review → **squash merge** to `main`.

---

## Allowed Prefixes

There are exactly **9** allowed branch prefixes. A branch name MUST start with one of them.

| Prefix | When to use | Maps to commit type(s) |
|---|---|---|
| `feat/` | New feature or capability for users/projects | `feat` |
| `fix/` | Bug fix — corrects broken behavior | `fix` |
| `docs/` | Documentation only (README, ADR, guides, comments) | `docs` |
| `chore/` | Maintenance, deps, tooling, housekeeping — no behavior change | `chore` |
| `refactor/` | Restructure code without changing behavior | `refactor` |
| `test/` | Add or improve tests, fixtures, harnesses | `test` |
| `ci/` | CI/CD pipelines, workflows, runners, automation | `ci` |
| `security/` | Security fix, hardening, secret handling, dependency CVE | `security` |
| `release/` | Release prep, version bumps, changelogs, tagging | `build` |

> Commit types span a slightly wider set than prefixes: `feat fix docs chore refactor test ci security perf build`. Use the prefix that best frames the branch's primary intent; `perf` work typically rides under `refactor/` or `feat/`, and `build` work under `release/` or `chore/`.

---

## Naming Rules

```
<prefix>/<short-kebab-name>
```

- **kebab-case only** — lowercase words joined by hyphens (`fix/login-redirect-loop`).
- **Short** — describe the change in a few words; trim filler. Aim for ≤ 5 words.
- **No spaces, no underscores, no uppercase, no trailing slash.**
- The slug should read as a phrase a teammate understands at a glance.

**Examples**

```
feat/proof-receipt-uploader
fix/login-redirect-loop
docs/branching-standard
chore/bump-node-22
refactor/event-log-replay
test/fsm-transition-cases
ci/squash-merge-guard
security/scrub-vault-logs
release/v0-4-0
```

---

## No Direct Commits to Main

- `main` is protected and accepts changes **only** via squash-merged PRs.
- Every PR branch MUST be created from the **latest** `main`.
- **Squash merge only** — one PR becomes one clean commit on `main`. No merge commits, no rebase-merge, no force-push to `main`.
- A PR is not mergeable until CI passes, review is complete, comments are resolved, and proof is attached.

---

## How Branches Map to Commits

The branch prefix and the Conventional Commit type are two views of the same intent and should agree.

**Conventional Commit format:**

```
type(optional-scope): subject
```

- `type` is one of: `feat fix docs chore refactor test ci security perf build`
- subject is **imperative, lowercase, no trailing period**
- body bullets and trailers (e.g. `Co-Authored-By:`) are allowed

A `fix/` branch carries `fix:` commits; a `feat/` branch carries `feat:` commits, and so on. Mixed-intent branches are a smell — split them. Because merges are squashed, the **PR title** becomes the commit on `main`, so it MUST also follow Conventional Commit format.

**Example end to end**

```
branch:   fix/login-redirect-loop
commit:   fix(auth): stop redirect loop on expired session
PR title: fix(auth): stop redirect loop on expired session
merge:    squash → one fix commit on main
```
