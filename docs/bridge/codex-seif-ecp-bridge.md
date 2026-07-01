# Codex-SEIF-ECP continuity bridge design

Status: dry-run design

## Goal

Prepare sanitized Codex task packets from GitHub issue metadata, repo state, SEIF continuity snapshot, ECP context packet, allowed docs, test commands, and safety constraints.

## Allowed input to Codex

- repo path
- issue id
- branch name
- safe architecture docs
- test commands
- current status matrix
- ECP task packet
- SEIF continuity snapshot

## Denied input

- `.env` files
- vault paths
- private keys
- tokens
- production credentials
- billing secrets
- Stripe webhook secret
- database service credentials

## Packet lifecycle

1. StratosAgent/Hermes-like reporting creates task intent.
2. ECP compiles safe context packet.
3. SEIF contributes continuity snapshot and policy constraints.
4. Bridge applies allowlist and denylist.
5. Dry-run emits packet manifest and exclusion log.
6. Codex performs work.
7. Result packet records commands, tests, touched files, assumptions, and evidence.
8. SEIF writes deterministic receipt.
9. GitHub issue/PR receives summary.

## Required red-team tests

- path traversal
- symlink leakage
- `.env` inclusion
- vault path inclusion
- hidden token in config
- gitignored file leakage
- oversized packet
- prompt injection from repo docs
- malicious issue text
- command injection in metadata

## First implementation boundary

Dry-run only. No production secrets, no deploy, no automatic GitHub writes.
