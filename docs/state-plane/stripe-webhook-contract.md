# Stripe webhook provisioning contract

Status: draft

## Role boundaries

Stripe is the payment signal. Efficient Labs Postgres plus SEIF is the entitlement authority.

Webhook handling must verify Stripe signatures before parsing privileged events. Unverified events are denied and logged as security events. No Stripe secret is committed or printed.

## Accepted events

- `customer.created`
- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`

## Processing rules

1. Verify webhook signature.
2. Deduplicate by Stripe event id: insert into `stripe_events` (`event_id` primary key, `insert ... on conflict do nothing`) before any side effect; a conflict means the event was already received and processing stops. This covers retries and replays even before a subscription row exists.
3. Fetch current subscription truth when a subscription id is present.
4. Map price id to Efficient Labs plan through founder-provisioned price map.
5. Write subscription mirror row.
6. Recompute entitlements from current subscription state, not event deltas.
7. Write SEIF receipt for every entitlement transition.
8. Emit audit log and usage/security event when applicable.
9. Return retryable 5xx on transient DB/Stripe/fetch/mirror failures.
10. Never silently downgrade an active subscription with unmapped price to free.

## Failure modes

- Missing verifier: fail closed.
- Bad signature: deny and log security event.
- Duplicate event: no-op after the `stripe_events` insert conflicts.
- Unmapped active price: retry and alert, no free record.
- Database unavailable: retry, no acknowledged entitlement mutation.
- SEIF receipt failure: fail closed for privileged entitlement changes.
