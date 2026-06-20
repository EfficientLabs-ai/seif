# GAEO — GitHub Enterprise Agent Organization

> **reality_state:** STANDALONE (spec) · **truth_class:** ARCHITECTURE · **target:** the GitHub projection of the SEIF control plane.
> The repository is the company. GitHub is the operating system. No model owns continuity — SEIF does, subject to Neo's sovereignty.

GAEO is **not a second system.** It is SEIF's control/evidence plane (task → event → artifact → claim → approval → receipt) rendered in GitHub's native primitives (Issues, PRs, Reviews, Projects, Discussions, ADRs). Everything below is enforced by GitHub mechanics where possible, not merely described.

---

## 0. Today-truth (honest reality — do not overclaim)
At v0.1, the three models do **not** have independent GitHub agency:
- **Claude Code (as `neo`) is the only executor** of `git`/`gh`.
- **Codex** runs `codex_reviewer` (read-only); its shell-exec sandbox is broken on this host → it cannot open PRs/run `gh`.
- **Gemini** is advisory text via CLI/MCP → no GitHub agency.

**Operating model now:** Claude is the hands; **Codex + Gemini are independent reviewers/validators whose verdicts are recorded into GitHub artifacts** (review comments, `Co-Authored-By` trailers, validation notes). Three-mind consensus is real today; **separate-identity autonomy** (each model with its own GitHub account + scoped token opening its own PRs) is `ARCHITECTURE`, gated on (a) per-model identities/tokens and (b) fixing/replacing Codex's exec sandbox. Do not render it as a `CLAIM` until both exist.

## 1. Roles (dynamic, recorded on each artifact)
| Agent | Charter |
|---|---|
| **Claude** | Chief Architect · Tech Lead · Product Strategist · Systems Designer · Docs Lead · long-term planning, architecture review, PR governance, risk & tech-debt analysis |
| **Codex** | Senior SWE · Security · QA · Refactoring · Test Author · CI/CD · implementation lead |
| **Gemini** | Research · Validation · Competitive intel · Performance · Requirements verification · benchmarking |

Ownership (Claude=architecture, Codex=implementation, Gemini=verification) **does not grant merge authority.** Verification is always mandatory; `neo` holds merge on protected branches.

## 2. Enforcement via GitHub primitives (mechanical, not trust-based)
The protocol becomes real only when GitHub *enforces* it:
- **Branch protection** on `main` (+ `develop`): no direct pushes, linear history, required reviews.
- **CODEOWNERS** → routes review by ownership area.
- **Required status checks** (Actions: build · test · security scan) → the "merge requirements" checklist, enforced.
- **Required ADR label / signed commits** → governance without trust.
- **`neo` = required approver on protected branches** → Human Sovereignty preserved.
- Repo creation, visibility flips, and `main` merges remain **protected actions** (`governance/protected_actions.yaml`).

## 3. Lifecycle (maps to SEIF FSM)
`Discovery → Planning → Implementation → Verification → Merge`, mirroring `DRAFT→PROPOSED→VALIDATED→AUTHORIZED→EXECUTING→VERIFYING→ACCEPTED`.
- **Discovery** → Issues / Discussions / ADRs (bugs, debt, security, perf, docs, deploy risks).
- **Planning** → Epic → Feature → Task → Subtask (GitHub Projects + Issues).
- **Implementation** → feature branch + PR (Problem · Solution · Files · Testing · Risks · Rollback · Verification · Affected systems · Dependencies).
- **Verification** → independent: Claude proposes → Codex implements → Gemini validates → Claude reviews → consensus. Builder is never sole authority.

## 4. Communication protocol
Agents communicate **exclusively** through GitHub artifacts: Issues, PR comments, Reviews, Discussions, Project updates, commit messages, ADR files, docs. **No hidden decisions, no undocumented work, no silent modifications.** Every action observable + auditable.

## 5. Commit & branch standards
- Commits: `type(scope): summary` — `feat`,`fix`,`refactor`,`test`,`docs`,`chore`,`perf`,`sec`.
- Branches: `main` (production-ready) · `develop` (integration) · `feature/*` · `hotfix/*` · `research/*`.
- Review categories: correctness, performance, security, maintainability, readability, scalability, reliability, observability, documentation, test coverage, backwards-compat, failure recovery.

## 6. Merge requirements (PR cannot merge until)
✓ build · ✓ tests · ✓ security scan · ✓ docs updated · ✓ ADR updated if required · ✓ independent verification complete · ✓ rollback documented · ✓ release notes · ✓ consensus · ✓ `neo` approval on protected branches.

## 7. Org boards — **semantic now, service later** (NOT_IN_V0_1 discipline)
Adopt as **labels + issue templates + conventions** immediately; promote any one to a standing process only when volume proves it earns its cost:
- **ARB** (Architecture Review Board) — owns RFCs/ADRs/standards/design coherence.
- **CAB** (Change Advisory Board) — production-impacting changes, migrations, schema/security-sensitive work.
- **ICS** (Incident Command) — outages, regressions, failed deploys, postmortems.
- **EIU** (Engineering Intelligence Unit) — mines commits/issues/PRs/docs for bottlenecks, duplication, optimization.
- **RMS** (Repository Memory System) — GitHub as institutional memory; every decision/tradeoff/rollback/lesson searchable.

## 8. Enterprise functions beyond coding (service-later)
PM (roadmaps, prioritization, cost), TPM (milestones, blockers, dependencies), SecOps (vulns, secrets, threat models), SRE (uptime, error rates, regressions, incidents), Research (competitors, papers, benchmarks), QA (unit→chaos→security tests), DevOps (Docker/K8s/Terraform/DNS/monitoring), Knowledge Mgmt (decision/architecture history, postmortems). Each is a **role hat + artifact type**, not a standing daemon in v0.1.

## 9. Metrics (track once events flow)
velocity · lead/cycle time · deploy frequency · failure rate · recovery time · coverage · bug density · PR review/merge time · open/closed issues · tech debt · infra cost · security-risk score · repo-health score. Derived from GitHub events — a **projection**, never the source of truth.

## 10. v0.1 first slice (the smallest enforceable loop — start here)
One repo: `Issue → feature branch → PR → Codex + Gemini reviews recorded → required checks green → neo merges`. Everything in §7–§9 enters as labels/templates first. The "engineering organization" **emerges from proven primitives**, it is not declared into existence.

**Gated next steps (founder decisions):** which org owns new repos (`EfficientLabs-ai` vs `Neo-The-Architect`); per-model GitHub identities now vs. Claude-as-hands + recorded reviews first; Codex exec-sandbox fix for true autonomy.
