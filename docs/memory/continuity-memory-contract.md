# ContinuityMemory shared contract

Status: draft

## Authority

StratosAgent owns the memory authority contract. SEIF governs privileged writes and receipts. ECP packages portable context and migration records. Atmosphere transports signed work and receipts.

## Interface

```ts
interface ContinuityMemory {
  writeEvent(event: MemoryEvent): Promise<MemoryReceipt>
  readContext(query: ContextQuery): Promise<ContextSnapshot>
  checkpoint(scope: CheckpointScope): Promise<CheckpointReceipt>
  attachEvidence(evidence: EvidenceArtifact): Promise<EvidenceReceipt>
  promoteToGraph(eventIds: string[]): Promise<GraphPromotionReceipt>
}
```

## Adapter boundaries

- L1 Redis: hot state and short-lived working set.
- L2 ledger/JSONL/Postgres: append-only episodic events.
- L3 graph: deterministic relationships, dependencies, impact, reusable lessons.
- L4 checkpoint/Postgres: durable snapshots, restore points, state-plane persistence.

## Migration plan

1. Keep SEIF `memory/tripartite.py` as the proving implementation.
2. Add StratosAgent adapter that maps operating-core traces/evals/lessons to `MemoryEvent`.
3. Add Atmosphere adapter that maps receipt/job/security events to `MemoryEvent`.
4. Store portable packet references through ECP packet hashes.
5. Promote evidence-backed events to graph only after SEIF approval.
6. Add conformance tests per repo before replacing local APIs.

## Non-goals

- Do not rewrite all memory systems in the first PR.
- Do not trust model summaries as truth.
- Do not allow memory writes without receipts for privileged state.
