# NOT IN v0.1 — Scope Guard

The optimal system is the **smallest inspectable kernel** that can safely coordinate replaceable intelligence, preserve evidence, and measurably improve. Anything below is **explicitly deferred**. Adding any of it requires a decision record + a reason it can't be done with the v0.1 substrate. Default answer to "should we add X" is **no**.

| Deferred | Why deferred | v0.1 substitute |
|----------|--------------|-----------------|
| Temporal (durable workflow engine) | operational cost; not yet justified by volume | Postgres/SQLite/JSONL event log + idempotency keys + receipts |
| OPA / Rego policy engine | policy volume small | small auditable policy module + `protected_actions.yaml` |
| Neo4j / RedisGraph | no graph workload that Postgres can't project | derived graph **projection** from events (read-only) |
| RDF-star temporal knowledge graph | premature | bi-temporal fields on `claim` records (valid_time + recorded_time) |
| Blackboard / Linda tuple-space **runtime** | new runtime dependency | typed task + event tables (semantic adoption only) |
| Actor model / Erlang-OTP supervisor **runtime** | existing PM2/systemd + restart already give supervision | adopt "let it crash" semantically; isolated Linux users |
| A2A protocol (external agent interop) | no external agents to talk to yet | internal task/event/approval contracts |
| MCP as internal bus | MCP is for tools, not internal authz | kernel owns task/event/evidence |
| QUBO / quantum-inspired routing | no proof of advantage; fashion risk | deterministic scoring → CP-SAT/SMT baseline; quantum only as benchmarked CHALLENGER |
| TLA+ full-system formalization | don't formalize the whole company | TLA+/SMT only on: protected-action authz, FSM transitions, scheduler/failover invariants |
| PQC signing (ML-DSA-65 / ML-KEM-768) | non-deterministic sigs + lib overhead before identity need | `sha256` content hashes on events/receipts; PQC when cross-node trust is real |
| Crypto-key actor identity (actor keys, rotation, revocation) | no cross-node trust need yet | v0.1 actor identity = OS principal (Linux user + Tailscale) |
| Self-modifying / self-replacing enforcement | unsafe | **self-proposing** only: proposal → challenger → tests → review → shadow → Neo approval → HARNESS_Cn |
| 12-service "fabric" deployment | sprawl; uninspectable TCB | 7-function microkernel over existing substrate |
| Graphical command-center (write path) | must never become a path around policy | read-only projection only, after reliable events exist |
| Making SEIF public / Apache OSS | irreversible; conflicts with HOLD-publish / moat-private | build private; draw IP line; founder gate before any public push |

**Rule:** "quantum" appears in production docs only for a defined cryptographic standard, algorithm, mathematical formulation, or real quantum hardware — never as a synonym for uncertainty.
