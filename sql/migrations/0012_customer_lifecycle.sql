-- Customer lifecycle data is separate/additive so it can be applied after core tenant migrations.
create table if not exists customer_lifecycle_records (
  customer_id uuid primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  onboarding_status text not null default 'NOT_STARTED' check (onboarding_status in ('NOT_STARTED','COLLECTING_INFO','CONNECTING','TESTING','READY_FOR_ACTIVATION','ACTIVE','BLOCKED')),
  lifecycle_status text not null default 'ONBOARDING' check (lifecycle_status in ('ONBOARDING','ACTIVE','AT_RISK','RENEWAL_DUE','CHURNED')),
  profile jsonb not null default '{}'::jsonb,
  integrations jsonb not null default '{}'::jsonb,
  health_score integer not null default 0 check (health_score between 0 and 100),
  last_activity_at timestamptz,
  activated_at timestamptz,
  unresolved_issues integer not null default 0 check (unresolved_issues >= 0),
  automation_failures_7d integer not null default 0 check (automation_failures_7d >= 0),
  usage_drop_percent numeric(5,2) not null default 0 check (usage_drop_percent between 0 and 100),
  renewal_date date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_lifecycle_org_status on customer_lifecycle_records(organization_id,lifecycle_status);
create index if not exists idx_lifecycle_renewal on customer_lifecycle_records(renewal_date) where lifecycle_status in ('ACTIVE','AT_RISK','RENEWAL_DUE');

create table if not exists customer_lifecycle_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  customer_id uuid not null references customer_lifecycle_records(customer_id) on delete cascade,
  event_type text not null,
  idempotency_key text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(organization_id,idempotency_key)
);
create index if not exists idx_lifecycle_events_customer on customer_lifecycle_events(organization_id,customer_id,created_at desc);

alter table customer_lifecycle_records enable row level security;
alter table customer_lifecycle_events enable row level security;
create policy lifecycle_record_member_access on customer_lifecycle_records for all
  using (exists (select 1 from organization_members m where m.organization_id = customer_lifecycle_records.organization_id and m.user_id = auth.uid()))
  with check (exists (select 1 from organization_members m where m.organization_id = customer_lifecycle_records.organization_id and m.user_id = auth.uid()));
create policy lifecycle_event_member_read on customer_lifecycle_events for select
  using (exists (select 1 from organization_members m where m.organization_id = customer_lifecycle_events.organization_id and m.user_id = auth.uid()));
-- Write lifecycle events through a trusted backend/service role after tenant and idempotency checks.
