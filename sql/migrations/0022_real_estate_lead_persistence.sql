-- v49: durable, tenant-scoped real-estate lead snapshots, idempotency and audit events.
-- Apply only in a dedicated staging project first. External provider calls are out of scope.
create table if not exists public.real_estate_leads (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  lead_id text not null check (length(trim(lead_id)) between 1 and 250),
  state text not null check (length(trim(state)) between 1 and 80),
  payload jsonb not null default '{}'::jsonb check (jsonb_typeof(payload) = 'object'),
  version bigint not null default 1 check (version >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (organization_id, lead_id)
);
create index if not exists real_estate_leads_queue_idx
  on public.real_estate_leads (organization_id, state, updated_at desc);

create table if not exists public.real_estate_lead_idempotency (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  idempotency_key text not null check (length(trim(idempotency_key)) between 1 and 250),
  request_digest text not null check (request_digest ~ '^[a-f0-9]{64}$'),
  lead_id text not null check (length(trim(lead_id)) between 1 and 250),
  resulting_version bigint not null check (resulting_version >= 1),
  created_at timestamptz not null default now(),
  primary key (organization_id, idempotency_key),
  foreign key (organization_id, lead_id)
    references public.real_estate_leads(organization_id, lead_id) on delete cascade
);

create table if not exists public.real_estate_lead_events (
  event_id text primary key check (event_id ~ '^[a-f0-9]{64}$'),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  lead_id text not null,
  event_type text not null check (length(trim(event_type)) between 1 and 100),
  event_payload jsonb not null check (jsonb_typeof(event_payload) = 'object'),
  created_at timestamptz not null default now(),
  unique (organization_id, lead_id, event_id),
  foreign key (organization_id, lead_id)
    references public.real_estate_leads(organization_id, lead_id) on delete cascade
);
create index if not exists real_estate_lead_events_timeline_idx
  on public.real_estate_lead_events (organization_id, lead_id, created_at, event_id);

alter table public.real_estate_leads enable row level security;
alter table public.real_estate_lead_idempotency enable row level security;
alter table public.real_estate_lead_events enable row level security;
revoke all on table public.real_estate_leads, public.real_estate_lead_idempotency,
  public.real_estate_lead_events from public, anon, authenticated;
grant select, insert, update, delete on table public.real_estate_leads to service_role;
grant select, insert on table public.real_estate_lead_idempotency to service_role;
grant select, insert on table public.real_estate_lead_events to service_role;

-- Audit is append-only for service_role at the privilege layer; do not grant UPDATE/DELETE.
-- Service-role access bypasses RLS, so call only from a trusted backend that validates
-- the authenticated user's organization. Never expose the service-role key to browsers/n8n inputs.
