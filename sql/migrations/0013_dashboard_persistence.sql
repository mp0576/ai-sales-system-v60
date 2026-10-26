-- Durable dashboard entities. Apply after 0001_core.sql and 0002_rls.sql.
create table if not exists approval_requests (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  action_id uuid references actions(id) on delete set null,
  action_type text not null,
  summary text not null,
  risk_level text not null check (risk_level in ('LOW','MEDIUM','HIGH','CRITICAL')),
  status text not null default 'PENDING' check (status in ('PENDING','APPROVED','REJECTED','EXPIRED')),
  requested_by uuid,
  resolved_by uuid,
  resolution_reason text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  updated_at timestamptz not null default now()
);
create index if not exists idx_approval_requests_org_status on approval_requests(organization_id,status,created_at desc);

create table if not exists execution_logs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  execution_id text not null,
  workflow text not null,
  status text not null check (status in ('QUEUED','RUNNING','SUCCEEDED','RETRYING','FAILED','DEAD_LETTER')),
  duration_ms integer check (duration_ms is null or duration_ms >= 0),
  error_code text,
  created_at timestamptz not null default now(),
  unique (organization_id,execution_id)
);
create index if not exists idx_execution_logs_org_created on execution_logs(organization_id,created_at desc);

create table if not exists dashboard_audit_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  actor_user_id uuid,
  event_type text not null check (event_type in ('APPROVAL_APPROVED','APPROVAL_REJECTED','DASHBOARD_VIEWED','EXPORT_REQUESTED')),
  target_type text,
  target_id text,
  reason text,
  created_at timestamptz not null default now()
);
create index if not exists idx_dashboard_audit_org_created on dashboard_audit_events(organization_id,created_at desc);

alter table approval_requests enable row level security;
alter table execution_logs enable row level security;
alter table dashboard_audit_events enable row level security;
create policy approval_member_select on approval_requests for select using (is_org_member(organization_id));
create policy approval_manager_update on approval_requests for update
  using (exists (select 1 from organization_members m where m.organization_id=approval_requests.organization_id and m.user_id=auth.uid() and upper(m.role) in ('OWNER','ADMIN','MANAGER')))
  with check (exists (select 1 from organization_members m where m.organization_id=approval_requests.organization_id and m.user_id=auth.uid() and upper(m.role) in ('OWNER','ADMIN','MANAGER')));
create policy execution_member_select on execution_logs for select using (is_org_member(organization_id));
create policy dashboard_audit_member_select on dashboard_audit_events for select using (is_org_member(organization_id));
create policy dashboard_audit_member_insert on dashboard_audit_events for insert with check (is_org_member(organization_id) and actor_user_id = auth.uid());

-- Resolve + audit atomically; called through PostgREST RPC with the user's JWT.
create or replace function public.resolve_dashboard_approval(
  p_organization_id uuid,
  p_approval_id uuid,
  p_approved boolean,
  p_reason text
) returns setof approval_requests
language plpgsql security invoker set search_path = public as $$
declare
  resolved approval_requests;
begin
  if length(trim(coalesce(p_reason,''))) < 3 then
    raise exception 'A decision reason of at least 3 characters is required';
  end if;
  update approval_requests
     set status = case when p_approved then 'APPROVED' else 'REJECTED' end,
         resolved_at = now(), resolved_by = auth.uid(),
         resolution_reason = trim(p_reason), updated_at = now()
   where id = p_approval_id and organization_id = p_organization_id and status = 'PENDING'
   returning * into resolved;
  if not found then return; end if;
  insert into dashboard_audit_events(organization_id, actor_user_id, event_type, target_type, target_id, reason)
  values (p_organization_id, auth.uid(),
          case when p_approved then 'APPROVAL_APPROVED' else 'APPROVAL_REJECTED' end,
          'approval_request', p_approval_id::text, trim(p_reason));
  return next resolved;
end;
$$;
