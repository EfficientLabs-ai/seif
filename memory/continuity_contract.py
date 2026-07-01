#!/usr/bin/env python3
"""ContinuityMemory target contract.

This is the next shared contract for SEIF, StratosAgent, and Atmosphere. It is
not an adapter rewrite. It gives each implementation a small conformance target
for owned, receipt-backed memory operations.
"""

REQUIRED_METHODS = [
    "write_event",
    "read_context",
    "checkpoint",
    "attach_evidence",
    "promote_to_graph",
]

TS_INTERFACE = """interface ContinuityMemory {
  writeEvent(event: MemoryEvent): Promise<MemoryReceipt>
  readContext(query: ContextQuery): Promise<ContextSnapshot>
  checkpoint(scope: CheckpointScope): Promise<CheckpointReceipt>
  attachEvidence(evidence: EvidenceArtifact): Promise<EvidenceReceipt>
  promoteToGraph(eventIds: string[]): Promise<GraphPromotionReceipt>
}"""


def conforms(obj):
    """Return (ok, missing) for a Python adapter using snake_case names."""
    missing = [name for name in REQUIRED_METHODS if not callable(getattr(obj, name, None))]
    return (not missing, missing)


def _selftest():
    class Good:
        def write_event(self, event): pass
        def read_context(self, query): pass
        def checkpoint(self, scope): pass
        def attach_evidence(self, evidence): pass
        def promote_to_graph(self, event_ids): pass

    class Bad:
        def write_event(self, event): pass

    ok, missing = conforms(Good())
    assert ok and missing == []
    ok, missing = conforms(Bad())
    assert not ok and missing == ["read_context", "checkpoint", "attach_evidence", "promote_to_graph"]
    print("continuity contract selftest PASS")


if __name__ == "__main__":
    _selftest()
