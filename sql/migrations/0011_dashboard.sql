-- Dashboard persistence contract. Review and apply only after the tenant/RLS migrations.
create table if not exists dashboard_audit_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  actor_user_id uuid,
  event_type text not null check (event_type in ('APPROVAL_APPROVED','APPROVAL_REJECTED','DASHBOARD_VIEWED','EXPORT_REQUESTED')),
  target_type text,
  target_id text,
  reason text,
  request_id text,
  created_at timestamptz not null default now()
);
create index if not exists idx_dashboard_audit_org_created on dashboard_audit_events(organization_id, created_at desc);
alter table dashboard_audit_events enable row level security;
create policy dashboard_audit_member_read on dashboard_audit_events for select
  using (exists (select 1 from organization_members m where m.organization_id = dashboard_audit_events.organization_id and m.user_id = auth.uid()));
-- Inserts should be performed by a trusted backend that validates actor role and records the authenticated user.
