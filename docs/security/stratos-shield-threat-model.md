# Stratos Shield threat model

Status: draft

## Security claim language

Do not claim zero security risk. Use this language:

- deny-by-default
- least privilege
- sandboxed execution
- auditable actions
- recoverable state
- cryptographic receipts
- policy-governed autonomy
- blast-radius-limited failures

## Inspection pipeline

Untrusted input enters quarantine, then type detection, static scanning, policy evaluation, optional LLM advisory review, sandbox trial, SEIF/human approval, signed promotion, execution, receipt, monitoring, and rollback.

## Object coverage

### Prompts

Threats: prompt injection, hierarchy override, secret exfiltration request, tool escalation.

Controls: instruction hierarchy checks, dangerous intent detection, capability diff, no privileged execution from raw model text.

### Files

Threats: malware, hidden payloads, parser exploits, embedded secrets.

Controls: hash first, secret scan, file type allowlist, parser sandbox, no auto-execute.

### Images

Threats: OCR prompt injection, QR/link exfiltration, metadata leakage, parser exploit.

Controls: metadata stripping, OCR quarantine, no auto-follow embedded URLs, isolated parser.

### Links

Threats: phishing, redirect chains, credentialed fetch, drive-by downloads.

Controls: no credentialed fetch by default, redirect inspection, domain policy, content sandbox.

### Repos

Threats: malicious install scripts, dependency confusion, secrets, license traps, supply-chain tampering.

Controls: clone into no-network sandbox, secret scan, dependency scan, SBOM, install script quarantine, signed promotion.

### Skills

Threats: overbroad capabilities, forged publisher, hidden network/file access, prompt payloads.

Controls: manifest validation, publisher identity, capability declaration, permission diff, sandbox execution, approval receipt, revocation.

### Model outputs

Threats: command injection, fabricated authority, unsafe code, insecure output handling.

Controls: schema validation, policy check, dangerous command detection, human approval for privileged writes, never direct execute.

### Tool calls

Threats: command injection, path traversal, secret access, egress abuse.

Controls: argument schemas, allowlisted tools, path jail, egress policy, SEIF protected-action checks, receipts.

## P0 blockers before production claims

- Authenticated Atmosphere control sessions.
- Worker or process isolation for untrusted skill execution.
- Resource limits for CPU, memory, file, and network.
- Structured security events in Postgres.
- SEIF receipt for every promoted artifact.
