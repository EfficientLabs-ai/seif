-- Efficient Labs sovereign state plane initial schema.
-- Target: self-hosted Postgres. No secrets belong in this schema.

create extension if not exists pgcrypto;

create table if not exists organizations (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  name text not null,
  plan text not null default 'free',
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  display_name text,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists organization_memberships (
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  role text not null check (role in ('owner','admin','member','viewer')),
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

create table if not exists workspaces (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  slug text not null,
  name text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, slug)
);

create table if not exists stripe_customers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  stripe_customer_id text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists subscriptions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  stripe_subscription_id text unique,
  stripe_customer_id text,
  price_id text,
  plan text not null default 'free',
  state text not null check (state in ('pending_payment','paid_unprovisioned','provisioning','active','past_due','suspended','canceled','failed_needs_review')),
  current_period_end timestamptz,
  last_stripe_event_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists entitlements (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  workspace_id uuid references workspaces(id) on delete cascade,
  key text not null,
  value jsonb not null default '{}'::jsonb,
  source text not null check (source in ('free_floor','stripe','founder_grant','migration','manual_review')),
  valid_from timestamptz not null default now(),
  valid_until timestamptz,
  seif_receipt_id uuid,
  created_at timestamptz not null default now(),
  unique (organization_id, workspace_id, key)
);

create table if not exists agent_identities (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  workspace_id uuid references workspaces(id) on delete cascade,
  agent_kind text not null check (agent_kind in ('stratos','seif','logos','atmosphere','codex','claude','external')),
  public_identity text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  unique (organization_id, public_identity)
);

create table if not exists seif_receipts (
  id uuid primary key default gen_random_uuid(),
  receipt_hash text not null unique,
  actor_id text not null,
  action text not null,
  subject text,
  input_hash text,
  output_hash text,
  previous_receipt_hash text,
  receipt_body jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists ecp_packets (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references organizations(id) on delete cascade,
  workspace_id uuid references workspaces(id) on delete cascade,
  packet_hash text not null unique,
  packet_kind text not null check (packet_kind in ('task','result','migration','continuity','evidence')),
  schema_version text not null,
  storage_uri text not null,
  seif_receipt_id uuid references seif_receipts(id),
  created_at timestamptz not null default now()
);

create table if not exists audit_logs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references organizations(id) on delete cascade,
  actor_id text not null,
  action text not null,
  resource_type text not null,
  resource_id text,
  decision text not null check (decision in ('allow','deny','needs_review','error')),
  reason text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists usage_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references organizations(id) on delete cascade,
  workspace_id uuid references workspaces(id) on delete cascade,
  actor_id text,
  event_type text not null,
  units numeric not null default 0,
  cost_cents integer not null default 0,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists security_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references organizations(id) on delete cascade,
  workspace_id uuid references workspaces(id) on delete cascade,
  object_type text not null check (object_type in ('prompt','file','image','link','repo','skill','model_output','tool_call')),
  object_hash text,
  severity text not null check (severity in ('info','low','medium','high','critical')),
  decision text not null check (decision in ('quarantine','deny','allow','needs_review')),
  reason text not null,
  seif_receipt_id uuid references seif_receipts(id),
  created_at timestamptz not null default now()
);

create table if not exists migration_receipts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references organizations(id) on delete cascade,
  source_system text not null,
  source_export_hash text not null,
  ecp_packet_id uuid references ecp_packets(id),
  status text not null check (status in ('captured','normalized','verified','failed','rejected')),
  seif_receipt_id uuid references seif_receipts(id),
  created_at timestamptz not null default now()
);

create index if not exists audit_logs_org_created_idx on audit_logs (organization_id, created_at desc);
create index if not exists usage_events_org_created_idx on usage_events (organization_id, created_at desc);
create index if not exists security_events_org_created_idx on security_events (organization_id, created_at desc);
create index if not exists ecp_packets_workspace_created_idx on ecp_packets (workspace_id, created_at desc);
