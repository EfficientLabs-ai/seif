# SEIF v0.2 — Non-Goals (what we are deliberately NOT building now)

Date: 2026-06-22. Per the founder directive. Building these now would add complexity without attacking the
one measured weakness (a sufficiently independent, discriminative approximation of ground truth).

## Not building in v0.2
- **MCTS / LATS / I-MCTS / AdverMCTS.** Best-of-N first; implement MCTS only after defining state/action/
  tree-policy/expansion/rollout/reward/backprop/budget/termination AND proving measured benefit over Best-of-N.
- **More LLM judges voting on the same evidence.** Correlated opinions; our roadmap measured the panel as
  overrated. Add uncorrelated EXECUTABLE evidence instead. (Also: Gemini is deferred.)
- **Automatic skill promotion / perpetual self-improvement.** Skills are evidence-gated CANDIDATES: DOP
  shadow → held-out → human approval. No autonomous self-modification of the runtime.
- **Training a foundation model / PRM this wave.** PRMs stay advisory-only (never determine correctness or
  promotion), stored separate from executable evidence. Synthesia only after measured data + revenue.
- **Neo4j / RedisGraph / full RDF-star / full ATMS theorem engine.** SQLite + AST index + the minimal
  assumption graph first; adopt graph DBs only under measured query pressure.
- **Firecracker / microVMs.** Docker isolation is not yet the measured bottleneck.
- **Distributing across the Atmosphere.** Establish local correctness first; distribute later.
- **Composio/Nango deployment.** Governance layer is built; deployment + secrets are founder-gated (P3).
- **Autonomous production merges.** Founder remains the merge gate. No `git push --force` to main.
- **Replacing the official benchmark scorer / exposing gold patches or graded tests.**

## The one thing v0.2 IS for
Make the verifier closer to ground truth: Evidence Contract + candidate-blind tests + mutation adequacy +
multi-channel oracle, measured for false-accept/false-reject — then evidence-ranked Best-of-N.
