-- AI Sales System — core multi-tenant schema
create extension if not exists pgcrypto;

create table if not exists organizations (
  id uuid primary key default gen_random_uuid(), name text not null,
  slug text not null unique, status text not null default 'ACTIVE',
  timezone text not null default 'Europe/Lisbon', currency text not null default 'EUR',
  automation_enabled boolean not null default true, outbound_enabled boolean not null default false,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists organization_members (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null, role text not null default 'MEMBER', created_at timestamptz not null default now(),
  unique (organization_id, user_id)
);

create table if not exists contacts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references organizations(id) on delete cascade,
  name text, email text, phone text, metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists leads (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references organizations(id) on delete cascade,
  contact_id uuid references contacts(id) on delete set null,
  state text not null default 'NEW',
  fit_score integer not null default 0 check (fit_score between 0 and 25),
  problem_score integer not null default 0 check (problem_score between 0 and 25),
  intent_score integer not null default 0 check (intent_score between 0 and 30),
  capacity_score integer not null default 0 check (capacity_score between 0 and 20),
  facts jsonb not null default '{}'::jsonb, metadata jsonb not null default '{}'::jsonb,
  is_dnc boolean not null default false,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists events (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references organizations(id) on delete cascade,
  type text not null, lead_id uuid references leads(id) on delete set null,
  payload jsonb not null default '{}'::jsonb, idempotency_key text not null,
  created_at timestamptz not null default now(), unique (organization_id, idempotency_key)
);

create table if not exists outbox_events (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references organizations(id) on delete cascade,
  event_id uuid not null references events(id) on delete cascade, topic text not null,
  payload jsonb not null default '{}'::jsonb, status text not null default 'PENDING',
  available_at timestamptz not null default now(), attempts integer not null default 0,
  locked_at timestamptz, locked_by text, last_error text, created_at timestamptz not null default now(),
  unique (event_id)
);

create table if not exists actions (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references organizations(id) on delete cascade,
  lead_id uuid references leads(id) on delete set null, action_type text not null,
  status text not null default 'PENDING', input jsonb not null default '{}'::jsonb,
  output jsonb not null default '{}'::jsonb, idempotency_key text,
  requires_approval boolean not null default false, approved boolean not null default false,
  attempts integer not null default 0, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

create index if not exists idx_leads_org_state on leads(organization_id, state);
create index if not exists idx_events_org_created on events(organization_id, created_at desc);
create index if not exists idx_outbox_due on outbox_events(status, available_at);
create index if not exists idx_actions_org_status on actions(organization_id, status);
