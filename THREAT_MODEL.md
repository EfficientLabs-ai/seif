# SEIF v0.1 — Threat Model & Kernel Guarantees

Honest scope. The kernel makes specific guarantees and explicitly defers others. Adversarial-verify round **C0 (2026-06-20)** ran 5 attacks; outcomes below.

## Core assumption
**All mutations go through the kernel API, and `ledger/` is protected by OS permissions (owned by the kernel principal).** The kernel derives every security decision from the **ledger**, never from a caller-supplied object.

## Guaranteed in v0.1 (enforced + regression-tested)
| Guarantee | Mechanism |
|---|---|
| Malformed envelopes rejected | `validate()` (JSON Schema 2020-12) |
| Evidence-first | `claim` CLAIM needs non-empty evidence + verified; `artifact` ACCEPTED needs tests+reviewer+evidence — items `minLength:1` (no empty-string bypass) |
| Legal transitions only | `legal_transition()` in `transition_task` **and** in `append_event` (forged transition events rejected) |
| State is not spoofable by callers | `project_task()` reconstructs state from the event log; `transition_task` ignores caller-supplied `state`/`protected` |
| Protected-action gate | protected status recorded in `task.created`; AUTHORIZED requires an APPROVED approval whose `approver == neo` |
| Idempotency (global) | dedup on `idempotency_key` across all streams → no double-effect |
| Accidental-corruption + lazy-tamper + reorder detection | `verify_chain()` = hash match + `prev_hash` link + monotonic `seq` + no dup/gap |

## Deferred to NOT_IN_V0_1 (known limitations — do not overclaim)
- **Cryptographic authenticity.** `verify_chain()` proves *integrity*, not *authenticity*. An adversary with filesystem write access **as the kernel principal** can recompute the whole chain and forge history. The real fix is per-event signatures (**ML-DSA-65**, deferred). Until then, ledger integrity rests on OS perms + append-only discipline, **not** cryptography.
- **Append-only storage** (immutable file attrs / WORM).
- **Actor authentication** beyond OS principal (Linux user + Tailscale).

## C0 adversarial-verify results
| Attack | Result |
|---|---|
| Protected-gate bypass via lying task object | **FIXED** — ledger-derived protected status |
| Forged FSM transition via `append_event` | **FIXED** — legality enforced on append |
| Empty-string evidence defeats evidence-first | **FIXED** — `minLength:1` on evidence/reviewers |
| Idempotency stream bypass | **FIXED** — global dedup |
| Hash chain not tamper-proof (FS write needed) | **SCOPED** — partial (seq checks added); full fix = signatures (deferred) |
