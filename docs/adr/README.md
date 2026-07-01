# Architecture Decision Records (ADRs)

This folder holds the Efficient Labs decision log for the `EfficientLabs-ai/seif` repository. ADRs capture the significant decisions behind the system so the reasoning survives the decision — anyone reading the repo later can see not just *what* we built, but *why*.

## What an ADR is

An Architecture Decision Record is a short, dated document that records one significant decision: the context that forced it, the options considered, the choice made, and its consequences. ADRs are immutable once accepted — we do not rewrite history; we supersede it.

## When to write one

Write an ADR for any decision that is hard to reverse, affects more than one part of the system, or sets a precedent. In practice:

- **Architecture decisions** — system structure, data model, service boundaries, dependencies, build/deploy tooling, security posture.
- **Governance decisions** — operating standards, branch/merge policy, review gates, label taxonomy, ownership and authority.
- **Product decisions** — scope cuts, pricing, packaging, user-facing tradeoffs, deprecations.

If a future engineer would reasonably ask "why was it done this way?", the answer belongs in an ADR. Small, local, easily-reversed choices do not need one.

## Naming

One file per decision, using a zero-padded sequence number and a short kebab-case title:

```
NNNN-kebab-title.md
```

For example: `0001-record-architecture-decisions.md`, `0007-protect-main-branch.md`. The number is permanent and never reused, even if the ADR is later superseded.

## Lifecycle

Every ADR carries a status that moves in one direction:

- **proposed** — drafted and under discussion; not yet binding.
- **accepted** — agreed and in force; this is the current decision.
- **superseded** — replaced by a later ADR. The superseded record stays in the folder for history and links forward to its replacement (e.g. "Superseded by ADR-0012"); the replacement links back.

ADRs are never deleted. To change a decision, write a new ADR that supersedes the old one.

## Proposing an ADR

You can propose a new ADR by opening the **architecture_decision** issue form in this repository. Apply the relevant decision label (`architecture-decision`, `governance-decision`, or `product-decision`). Once discussion settles, the decision is captured as an `NNNN-kebab-title.md` file in this folder via a pull request that follows the repo's [GitHub operating standard](../../CONTRIBUTING.md), and its row is added to the log below.

## ADR Log

| ADR | Title | Status | Date | Supersedes / Superseded by |
|-----|-------|--------|------|----------------------------|
| 0001 | StratosAgent is the memory authority | proposed | 2026-06-28 | - |
| 0002 | Stripe plus self-hosted Postgres is the production state model | proposed | 2026-06-28 | - |
| 0003 | Two-plane VPS topology for launch | proposed | 2026-06-28 | - |
