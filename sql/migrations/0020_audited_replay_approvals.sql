-- v36: durable, tenant-scoped replay request/approval ledger. No provider dispatch occurs here.
alter table public.operational_exceptions add constraint operational_exceptions_org_id_unique unique (organization_id, id);
create table if not exists public.exception_replay_requests (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  exception_id uuid not null references public.operational_exceptions(id) on delete cascade,
  replay_number integer not null check (replay_number between 1 and 10),
  failure_class text not null check (failure_class in ('TRANSIENT_NETWORK','RATE_LIMITED','TEMPORARY_PROVIDER_ERROR')),
  external_outcome text not null check (external_outcome = 'NOT_APPLIED'),
  idempotency_key text not null check (length(trim(idempotency_key)) between 1 and 250),
  reason text not null check (length(trim(reason)) between 1 and 500),
  status text not null default 'PENDING_APPROVAL' check (status in ('PENDING_APPROVAL','APPROVED','REJECTED','CANCELLED')),
  requested_by uuid not null,
  approved_by uuid,
  requested_at timestamptz not null default now(),
  decided_at timestamptz,
  unique (organization_id, exception_id, replay_number),
  foreign key (organization_id, exception_id) references public.operational_exceptions(organization_id, id) on delete cascade
);
create index if not exists exception_replay_requests_queue_idx
  on public.exception_replay_requests(organization_id, status, requested_at);

create table if not exists public.exception_replay_audit (
  id bigint generated always as identity primary key,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  replay_request_id uuid not null references public.exception_replay_requests(id) on delete cascade,
  actor_user_id uuid not null,
  action text not null check (action in ('REQUESTED','APPROVED','REJECTED','CANCELLED')),
  note text not null check (length(trim(note)) between 1 and 500),
  created_at timestamptz not null default now()
);
create index if not exists exception_replay_audit_timeline_idx
  on public.exception_replay_audit(organization_id, replay_request_id, created_at);

alter table public.exception_replay_requests enable row level security;
alter table public.exception_replay_audit enable row level security;
revoke all on table public.exception_replay_requests, public.exception_replay_audit from public, anon, authenticated;
grant select, insert, update, delete on public.exception_replay_requests to service_role;
grant select, insert on public.exception_replay_audit to service_role;
grant usage, select on sequence public.exception_replay_audit_id_seq to service_role;

create or replace function public.request_exception_replay(
  p_organization_id uuid, p_exception_id uuid, p_actor_user_id uuid,
  p_replay_number integer, p_failure_class text, p_external_outcome text,
  p_idempotency_key text, p_reason text
) returns table(replay_request_id uuid, status text, duplicate boolean)
language plpgsql security definer set search_path = public, pg_temp as $$
declare ex public.operational_exceptions; actor_role text; rec public.exception_replay_requests; inserted boolean := false;
begin
  if p_organization_id is null or p_exception_id is null or p_actor_user_id is null then raise exception 'tenant, exception and actor are required'; end if;
  select m.role into actor_role from public.organization_members m where m.organization_id=p_organization_id and m.user_id=p_actor_user_id;
  if actor_role is null or actor_role not in ('OWNER','ADMIN','MANAGER') then raise exception 'manager-level membership required'; end if;
  if p_replay_number not between 1 and 10 then raise exception 'replay budget exceeded'; end if;
  if p_failure_class not in ('TRANSIENT_NETWORK','RATE_LIMITED','TEMPORARY_PROVIDER_ERROR') or p_external_outcome <> 'NOT_APPLIED' then raise exception 'failure is not eligible for replay request'; end if;
  if p_idempotency_key is null or length(trim(p_idempotency_key)) not between 1 and 250 then raise exception 'original idempotency key required'; end if;
  if p_reason is null or length(trim(p_reason)) not between 1 and 500 then raise exception 'audit reason required'; end if;
  select * into ex from public.operational_exceptions e where e.organization_id=p_organization_id and e.id=p_exception_id for update;
  if not found then raise exception 'exception not found for organization'; end if;
  if ex.status not in ('OPEN','ACKNOWLEDGED') then raise exception 'exception is not replayable in current state'; end if;
  if ex.code in ('PROVIDER_OUTCOME_UNKNOWN','PAYMENT_RECONCILIATION_REQUIRED','WEBHOOK_SIGNATURE_INVALID','HUMAN_APPROVAL_REQUIRED') then raise exception 'sensitive exception requires reconciliation'; end if;
  insert into public.exception_replay_requests(organization_id,exception_id,replay_number,failure_class,external_outcome,idempotency_key,reason,requested_by)
  values(p_organization_id,p_exception_id,p_replay_number,p_failure_class,p_external_outcome,trim(p_idempotency_key),trim(p_reason),p_actor_user_id)
  on conflict (organization_id,exception_id,replay_number) do nothing returning * into rec;
  inserted := found;
  if not inserted then
    select * into rec from public.exception_replay_requests r where r.organization_id=p_organization_id and r.exception_id=p_exception_id and r.replay_number=p_replay_number for update;
    if rec.idempotency_key <> trim(p_idempotency_key) then raise exception 'replay slot already exists with a different idempotency key'; end if;
  else
    insert into public.exception_replay_audit(organization_id,replay_request_id,actor_user_id,action,note)
    values(p_organization_id,rec.id,p_actor_user_id,'REQUESTED',trim(p_reason));
  end if;
  return query select rec.id,rec.status,not inserted;
end;
$$;

create or replace function public.decide_exception_replay(
  p_organization_id uuid, p_replay_request_id uuid, p_actor_user_id uuid,
  p_approve boolean, p_note text
) returns table(replay_request_id uuid, status text)
language plpgsql security definer set search_path = public, pg_temp as $$
declare actor_role text; rec public.exception_replay_requests; next_status text;
begin
  if p_organization_id is null or p_replay_request_id is null or p_actor_user_id is null then raise exception 'tenant, request and actor are required'; end if;
  if p_note is null or length(trim(p_note)) not between 1 and 500 then raise exception 'decision note required'; end if;
  select m.role into actor_role from public.organization_members m where m.organization_id=p_organization_id and m.user_id=p_actor_user_id;
  if actor_role is null or actor_role not in ('OWNER','ADMIN','MANAGER') then raise exception 'manager-level membership required'; end if;
  select * into rec from public.exception_replay_requests r where r.organization_id=p_organization_id and r.id=p_replay_request_id for update;
  if not found then raise exception 'replay request not found for organization'; end if;
  if rec.status <> 'PENDING_APPROVAL' then raise exception 'replay request already decided'; end if;
  if p_approve and rec.requested_by=p_actor_user_id then raise exception 'requester cannot approve own replay'; end if;
  next_status := case when p_approve then 'APPROVED' else 'REJECTED' end;
  update public.exception_replay_requests set status=next_status, approved_by=p_actor_user_id, decided_at=now() where id=rec.id;
  insert into public.exception_replay_audit(organization_id,replay_request_id,actor_user_id,action,note)
  values(p_organization_id,rec.id,p_actor_user_id,case when p_approve then 'APPROVED' else 'REJECTED' end,trim(p_note));
  return query select rec.id,next_status;
end;
$$;

revoke all on function public.request_exception_replay(uuid,uuid,uuid,integer,text,text,text,text) from public, anon, authenticated;
revoke all on function public.decide_exception_replay(uuid,uuid,uuid,boolean,text) from public, anon, authenticated;
grant execute on function public.request_exception_replay(uuid,uuid,uuid,integer,text,text,text,text) to service_role;
grant execute on function public.decide_exception_replay(uuid,uuid,uuid,boolean,text) to service_role;
