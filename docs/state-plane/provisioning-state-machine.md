# Provisioning state machine

Status: draft

## States

- `pending_payment`: checkout started; no platform entitlement beyond free floor.
- `paid_unprovisioned`: Stripe indicates payment/subscription success; local resources are not ready.
- `provisioning`: workspace, entitlements, agent identities, and receipts are being created.
- `active`: entitlement is usable.
- `past_due`: payment failure grace state; policy decides feature retention window.
- `suspended`: access restricted by payment, policy, or security event.
- `canceled`: subscription ended; free floor remains if account is valid.
- `failed_needs_review`: automated provisioning stopped and requires Neo/operator review.

## Transition rules

- Only verified Stripe events, founder grants, or SEIF-approved admin actions may transition paid states.
- Active or past-due subscriptions with unmapped price ids must not become free silently.
- Canceled subscriptions do not delete customer data.
- Privileged transitions write SEIF receipts.
- Rollback is a new transition with receipt, not mutation of history.

## Minimal transition table

| From | Event | To |
|---|---|---|
| pending_payment | checkout.session.completed | paid_unprovisioned |
| paid_unprovisioned | provisioning_started | provisioning |
| provisioning | provisioning_succeeded | active |
| provisioning | provisioning_failed | failed_needs_review |
| active | invoice.payment_failed | past_due |
| past_due | invoice.paid | active |
| active,past_due | customer.subscription.deleted | canceled |
| active,past_due | policy_suspend | suspended |
| suspended | policy_restore | active |
