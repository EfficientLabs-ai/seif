#!/usr/bin/env python3
"""SEIF Assumption Graph (v0.2 WP-G) — MINIMAL logical-invalidation layer (NOT a full ATMS theorem engine).

Worktrees handle PHYSICAL candidate isolation; this graph handles LOGICAL invalidation: when evidence
disproves an assumption, it determines which candidates are now stale, which cache entries must be
re-verified, which derived skills to quarantine, and which context packets are stale — **canonical main is
never touched** (no git reset; that's the worktree manager's and the promotion gate's job).

Event-sourced (append-only); `schemas/assumption-event.schema.json` is the wire format.
"""
NODE_TYPES = {"assumption", "evidence", "candidate", "test", "plan_node", "decision",
              "policy", "skill", "context_packet", "cache_entry"}
EDGE_TYPES = {"DEPENDS_ON", "SUPPORTS", "CONTRADICTS", "INVALIDATES", "TESTS",
              "DERIVED_FROM", "SUPERSEDES", "AUTHORIZED_BY"}
# how a downstream node reacts when an assumption it logically rests on is invalidated
_REACTION = {"candidate": "STALE", "skill": "QUARANTINED", "context_packet": "STALE",
             "cache_entry": "REVERIFY", "plan_node": "STALE", "decision": "REVIEW"}
# edges that propagate invalidation downstream (dependent ----edge---> assumption)
_PROPAGATING = {"DEPENDS_ON", "DERIVED_FROM"}


class AssumptionGraph:
    def __init__(self):
        self.nodes = {}                      # id -> {type, status, attrs}
        self.edges = []                      # (src, rel, dst)
        self.events = []                     # append-only log

    def add(self, node_id, node_type, status="ACTIVE", **attrs):
        if node_type not in NODE_TYPES:
            raise ValueError(f"unknown node type {node_type}")
        self.nodes[node_id] = {"type": node_type, "status": status, "attrs": attrs}
        self.events.append({"op": "add", "id": node_id, "type": node_type})
        return node_id

    def link(self, src, rel, dst):
        if rel not in EDGE_TYPES:
            raise ValueError(f"unknown edge type {rel}")
        if src not in self.nodes or dst not in self.nodes:
            raise ValueError(f"link endpoints must exist: {src}->{dst}")
        self.edges.append((src, rel, dst))
        self.events.append({"op": "link", "src": src, "rel": rel, "dst": dst})

    def _dependents(self, target):
        """Direct dependents: nodes with a propagating edge pointing AT `target`."""
        return [s for (s, rel, d) in self.edges if d == target and rel in _PROPAGATING]

    def invalidate(self, assumption_id, by_evidence=None):
        """Invalidate an assumption and propagate logical staleness to everything that rests on it
        (transitively). Returns the list of affected {id, type, new_status}. Canonical main is untouched."""
        if assumption_id not in self.nodes:
            raise ValueError(f"no such node {assumption_id}")
        self.nodes[assumption_id]["status"] = "INVALIDATED"
        self.events.append({"op": "invalidate", "id": assumption_id, "by_evidence": by_evidence})
        affected, seen, queue = [], {assumption_id}, list(self._dependents(assumption_id))
        while queue:
            nid = queue.pop(0)
            if nid in seen:
                continue
            seen.add(nid)
            node = self.nodes.get(nid)
            if not node:
                continue
            new_status = _REACTION.get(node["type"], "STALE")
            node["status"] = new_status
            self.events.append({"op": "cascade", "id": nid, "status": new_status, "from": assumption_id})
            affected.append({"id": nid, "type": node["type"], "new_status": new_status})
            queue.extend(self._dependents(nid))     # transitive
        return affected

    def status(self, node_id):
        return self.nodes[node_id]["status"]


def _selftest():
    g = AssumptionGraph()
    g.add("A1", "assumption", text="request body may be bytes")
    g.add("A3", "assumption", text="conversion only for text")
    g.add("cand4", "candidate")
    g.add("skill_x", "skill")
    g.add("cache_9", "cache_entry")
    g.add("ctx_2", "context_packet")
    g.add("t_bin", "test")
    g.add("ev1", "evidence")
    # cand4 rests on A1+A3; skill/cache/ctx derived from cand4; the test contradicts A3
    g.link("cand4", "DEPENDS_ON", "A1")
    g.link("cand4", "DEPENDS_ON", "A3")
    g.link("skill_x", "DERIVED_FROM", "cand4")
    g.link("cache_9", "DEPENDS_ON", "cand4")
    g.link("ctx_2", "DEPENDS_ON", "cand4")
    g.link("t_bin", "CONTRADICTS", "A3")     # non-propagating (informational)
    g.link("ev1", "INVALIDATES", "A3")

    affected = g.invalidate("A3", by_evidence="ev1")
    by = {a["id"]: a["new_status"] for a in affected}
    assert g.status("A3") == "INVALIDATED"
    assert by["cand4"] == "STALE", by
    assert by["skill_x"] == "QUARANTINED", by         # derived skill quarantined
    assert by["cache_9"] == "REVERIFY", by            # cache must be re-verified
    assert by["ctx_2"] == "STALE", by                 # context packet stale
    assert "t_bin" not in by, "CONTRADICTS is informational, not a propagating dependency"
    # transitive: invalidating A1 also restales cand4 and its dependents
    aff2 = g.invalidate("A1")
    assert any(a["id"] == "cand4" for a in aff2)
    print(f"assumption_graph selftest PASS — invalidation cascades (cand->STALE, skill->QUARANTINE, "
          f"cache->REVERIFY, ctx->STALE), transitive, main untouched")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("usage: assumption_graph.py --selftest")
