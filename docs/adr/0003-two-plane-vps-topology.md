# ADR-0003: Two-plane VPS topology for launch

Status: proposed
Date: 2026-06-28

## Context

The current VPS hosts the control/app/agent plane: SEIF, LOGOS, StratosAgent services, Atmosphere services, bridges, and PM2 processes. Paid users and self-hosted Postgres introduce stronger durability, backup, and blast-radius requirements.

## Decision

Do not merge VPS machines into one larger tangled environment. Keep separation of concerns.

VPS-1 is the control/app/agent plane.

VPS-2 is the state plane before external paid users:

- Postgres primary
- continuity checkpoint storage
- backup staging
- migration jobs
- database observability
- optional Redis/state services if promoted beyond local L1

## Network policy

- Public internet reaches only HTTPS edge routes.
- Database and Redis ports are never public.
- VPS-1 to VPS-2 traffic uses private Tailscale or WireGuard.
- Admin panels are private only.
- Backups are encrypted and copied off-host.

## Consequences

- Current P0 engineering does not require buying VPS-2.
- Stripe live mode and external paid users do require a state plane.
- Restore drills and backup receipts must pass before live billing.
