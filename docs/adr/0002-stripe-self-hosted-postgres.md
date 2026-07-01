# ADR-0002: Stripe plus self-hosted Postgres is the production state model

Status: proposed
Date: 2026-06-28

## Context

Efficient Labs needs payments, entitlements, continuity, audit logs, security events, and migration records. Managed Supabase is not the production source of truth because the business requires data ownership, schema portability, backup control, restore drills, and ECP export guarantees.

Stripe is still the correct payment rail. Stripe should not be the internal entitlement authority.

## Decision

Use Stripe for payment lifecycle and self-hosted Postgres for Efficient Labs state.

The corrected launch wording is:

Stripe plus self-hosted Postgres provisioning needs founder-provisioned vault bundle, price map, webhook secret, database migration plan, backup policy, and entitlement schema.

## Ownership boundaries

Stripe owns payment signals:

- customers
- checkout sessions
- subscriptions
- invoices
- payment success/failure
- tax/payment compliance workflow

Efficient Labs Postgres owns operating truth:

- users
- organizations
- workspaces
- subscriptions mirror
- entitlements
- agent identities
- SEIF receipts
- ECP packets
- audit logs
- usage events
- security events
- migration receipts

SEIF owns deterministic governance over entitlement changes and privileged actions.

## Consequences

- No production dependency on managed Supabase as source of truth.
- Postgres schemas and migrations must be first-class artifacts.
- Backups and restore drills are launch blockers.
- Stripe webhook ingestion must verify signatures and write SEIF receipts.
