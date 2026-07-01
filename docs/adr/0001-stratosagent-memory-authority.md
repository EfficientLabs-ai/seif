# ADR-0001: StratosAgent is the memory authority

Status: proposed
Date: 2026-06-28

## Context

Efficient Labs previously described Hermes as the layer that remembers. That is incorrect for the production doctrine. Hermes/OpenClaw/NemoClaw are useful reference patterns, but the Efficient Labs owned product must be StratosAgent: the sovereign agent runtime, user/developer interface, and memory authority.

SEIF remains the deterministic governance kernel. LOGOS remains probabilistic generation. ECP remains the portable context packet and migration format. Atmosphere remains the execution and communication fabric.

## Decision

StratosAgent is the memory authority and product surface for owned continuity.

Hermes is not a source of truth. Any Hermes-like chief-of-staff/reporting behavior is implemented as a StratosAgent capability that reads from governed memory contracts and SEIF receipts.

## Consequences

- Continuity APIs are owned by StratosAgent contracts.
- SEIF governs memory writes, evidence promotion, approvals, receipts, and rollback.
- ECP packages context and migration records for portability.
- Atmosphere transports signed work and receipts between agents/businesses.
- Product language must not say Hermes remembers.

## Required follow-up

- Implement the shared ContinuityMemory contract in StratosAgent, SEIF, and Atmosphere adapters.
- Update product docs to make StratosAgent the memory authority.
- Keep all privileged memory writes deny-by-default and receipt-backed.
