-- v33: durable, tenant-scoped exception center with atomic audit history.
create table if not exists public.operational_exceptions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  source_type text not null check (length(source_type) between 1 and 60),
  source_id text not null check (length(source_id) between 1 and 250),
  code text not null check (length(code) between 1 and 80),
  severity text not null check (severity in ('LOW','MEDIUM','HIGH','CRITICAL')),
  summary text not null check (length(summary) between 1 and 300),
  status text not null default 'OPEN' check (status in ('OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED')),
  assigned_to uuid,
  resolution_note text check (resolution_note is null or length(resolution_note) <= 500),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz,
  unique (organization_id, source_type, source_id)
);
create index if not exists operational_exceptions_queue_idx
  on public.operational_exceptions (organization_id, status, severity, created_at desc);

create table if not exists public.operational_exception_audit (
  id bigint generated always as identity primary key,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  exception_id uuid not null references public.operational_exceptions(id) on delete cascade,
  actor_user_id uuid,
  action text not null check (action in ('CREATED','ASSIGNED','ACKNOWLEDGED','RESOLVED','DISMISSED')),
  previous_status text,
  new_status text not null,
  note text check (note is null or length(note) <= 500),
  created_at timestamptz not null default now()
);
create index if not exists operational_exception_audit_timeline_idx
  on public.operational_exception_audit (organization_id, exception_id, created_at);

alter table public.operational_exceptions enable row level security;
alter table public.operational_exception_audit enable row level security;
revoke all on table public.operational_exceptions, public.operational_exception_audit from public, anon, authenticated;
grant select, insert, update, delete on public.operational_exceptions to service_role;
grant select, insert on public.operational_exception_audit to service_role;
grant usage, select on sequence public.operational_exception_audit_id_seq to service_role;

create or replace function public.create_operational_exception(
  p_organization_id uuid, p_source_type text, p_source_id text,
  p_code text, p_severity text, p_summary text
) returns table(exception_id uuid, status text, duplicate boolean)
language plpgsql security definer set search_path = public, pg_temp as $$
declare rec public.operational_exceptions; inserted boolean := false;
begin
  if p_organization_id is null then raise exception 'organization required'; end if;
  if p_source_type is null or length(trim(p_source_type)) not between 1 and 60 then raise exception 'invalid source type'; end if;
  if p_source_id is null or length(trim(p_source_id)) not between 1 and 250 then raise exception 'invalid source id'; end if;
  if p_code is null or length(trim(p_code)) not between 1 and 80 then raise exception 'invalid exception code'; end if;
  if p_severity not in ('LOW','MEDIUM','HIGH','CRITICAL') then raise exception 'invalid severity'; end if;
  if p_summary is null or length(trim(p_summary)) not between 1 and 300 then raise exception 'invalid summary'; end if;
  insert into public.operational_exceptions(organization_id,source_type,source_id,code,severity,summary)
  values(p_organization_id,trim(p_source_type),trim(p_source_id),trim(p_code),p_severity,trim(p_summary))
  on conflict (organization_id,source_type,source_id) do nothing returning * into rec;
  inserted := found;
  if not inserted then
    select * into rec from public.operational_exceptions e
     where e.organization_id=p_organization_id and e.source_type=trim(p_source_type) and e.source_id=trim(p_source_id) for update;
  else
    insert into public.operational_exception_audit(organization_id,exception_id,action,new_status)
    values(p_organization_id,rec.id,'CREATED',rec.status);
  end if;
  return query select rec.id, rec.status, not inserted;
end;
$$;

create or replace function public.transition_operational_exception(
  p_organization_id uuid, p_exception_id uuid, p_actor_user_id uuid,
  p_action text, p_assigned_to uuid default null, p_note text default null
) returns table(exception_id uuid, status text, assigned_to uuid)
language plpgsql security definer set search_path = public, pg_temp as $$
declare rec public.operational_exceptions; actor_role text; old_status text; new_status text; new_assignee uuid;
begin
  if p_organization_id is null or p_exception_id is null or p_actor_user_id is null then raise exception 'tenant, exception and actor are required'; end if;
  select m.role into actor_role from public.organization_members m
   where m.organization_id=p_organization_id and m.user_id=p_actor_user_id;
  if actor_role is null or actor_role not in ('OWNER','ADMIN','MANAGER') then raise exception 'manager-level membership required'; end if;
  select * into rec from public.operational_exceptions e
   where e.organization_id=p_organization_id and e.id=p_exception_id for update;
  if not found then raise exception 'exception not found for organization'; end if;
  old_status := rec.status; new_status := rec.status; new_assignee := rec.assigned_to;
  if rec.status in ('RESOLVED','DISMISSED') then raise exception 'terminal exception cannot be changed'; end if;
  if p_action='assign' then
    if p_assigned_to is null then raise exception 'assignee required'; end if;
    if not exists(select 1 from public.organization_members m where m.organization_id=p_organization_id and m.user_id=p_assigned_to) then raise exception 'assignee must belong to same organization'; end if;
    new_assignee := p_assigned_to;
  elsif p_action='acknowledge' then
    new_status := 'ACKNOWLEDGED';
  elsif p_action='resolve' then
    if p_note is null or length(trim(p_note)) not between 1 and 500 then raise exception 'resolution note required'; end if;
    new_status := 'RESOLVED';
  elsif p_action='dismiss' then
    if p_note is null or length(trim(p_note)) not between 1 and 500 then raise exception 'dismissal note required'; end if;
    new_status := 'DISMISSED';
  else raise exception 'unsupported exception action'; end if;
  update public.operational_exceptions e set status=new_status, assigned_to=new_assignee,
    resolution_note=case when p_action in ('resolve','dismiss') then trim(p_note) else e.resolution_note end,
    resolved_at=case when p_action in ('resolve','dismiss') then now() else e.resolved_at end,
    updated_at=now() where e.id=rec.id returning * into rec;
  insert into public.operational_exception_audit(organization_id,exception_id,actor_user_id,action,previous_status,new_status,note)
  values(p_organization_id,rec.id,p_actor_user_id,case p_action when 'assign' then 'ASSIGNED' when 'acknowledge' then 'ACKNOWLEDGED' when 'resolve' then 'RESOLVED' when 'dismiss' then 'DISMISSED' end,old_status,rec.status,left(nullif(trim(p_note),''),500));
  return query select rec.id,rec.status,rec.assigned_to;
end;
$$;

revoke all on function public.create_operational_exception(uuid,text,text,text,text,text) from public, anon, authenticated;
revoke all on function public.transition_operational_exception(uuid,uuid,uuid,text,uuid,text) from public, anon, authenticated;
grant execute on function public.create_operational_exception(uuid,text,text,text,text,text) to service_role;
grant execute on function public.transition_operational_exception(uuid,uuid,uuid,text,uuid,text) to service_role;
