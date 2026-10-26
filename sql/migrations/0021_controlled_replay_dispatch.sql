-- v37: atomically reserve approved replay requests before external dispatch.
-- A crashed/expired DISPATCHING lease is never auto-replayed; it is sent to reconciliation.
alter table public.exception_replay_requests
  drop constraint if exists exception_replay_requests_status_check;
alter table public.exception_replay_requests
  add constraint exception_replay_requests_status_check
  check (status in ('PENDING_APPROVAL','APPROVED','REJECTED','CANCELLED','DISPATCHING','EXECUTED','FAILED','RECONCILIATION_REQUIRED'));
alter table public.exception_replay_requests add column if not exists dispatch_worker_id text;
alter table public.exception_replay_requests add column if not exists dispatch_lease_until timestamptz;
alter table public.exception_replay_requests add column if not exists finished_at timestamptz;
alter table public.exception_replay_requests add column if not exists result_code text;

alter table public.exception_replay_audit drop constraint if exists exception_replay_audit_action_check;
alter table public.exception_replay_audit add constraint exception_replay_audit_action_check
  check (action in ('REQUESTED','APPROVED','REJECTED','CANCELLED','DISPATCH_CLAIMED','DISPATCH_SUCCEEDED','DISPATCH_FAILED','RECONCILIATION_REQUIRED'));

create or replace function public.claim_exception_replay(
  p_organization_id uuid, p_replay_request_id uuid, p_worker_id text, p_lease_seconds integer
) returns table(replay_request_id uuid, exception_id uuid, idempotency_key text, replay_number integer, failure_class text)
language plpgsql security definer set search_path = public, pg_temp as $$
declare rec public.exception_replay_requests; ex public.operational_exceptions;
begin
  if p_organization_id is null or p_replay_request_id is null or p_worker_id is null or length(trim(p_worker_id)) not between 1 and 120 then raise exception 'tenant, request and worker are required'; end if;
  if p_lease_seconds not between 15 and 300 then raise exception 'lease must be between 15 and 300 seconds'; end if;
  select * into rec from public.exception_replay_requests r
    where r.organization_id=p_organization_id and r.id=p_replay_request_id and r.status='APPROVED'
    for update skip locked;
  if not found then return; end if;
  select * into ex from public.operational_exceptions e
    where e.organization_id=p_organization_id and e.id=rec.exception_id for update;
  if not found or ex.status not in ('OPEN','ACKNOWLEDGED')
     or ex.code in ('PROVIDER_OUTCOME_UNKNOWN','PAYMENT_RECONCILIATION_REQUIRED','WEBHOOK_SIGNATURE_INVALID','HUMAN_APPROVAL_REQUIRED') then
    update public.exception_replay_requests set status='RECONCILIATION_REQUIRED', finished_at=now(), result_code='EXCEPTION_STATE_CHANGED'
      where id=rec.id;
    insert into public.exception_replay_audit(organization_id,replay_request_id,actor_user_id,action,note)
      values(p_organization_id,rec.id,rec.approved_by,'RECONCILIATION_REQUIRED','Exception state changed before dispatch');
    return;
  end if;
  update public.exception_replay_requests set status='DISPATCHING', dispatch_worker_id=trim(p_worker_id),
    dispatch_lease_until=now() + make_interval(secs => p_lease_seconds), result_code=null
    where id=rec.id;
  insert into public.exception_replay_audit(organization_id,replay_request_id,actor_user_id,action,note)
    values(p_organization_id,rec.id,rec.approved_by,'DISPATCH_CLAIMED','Approved replay atomically reserved by worker');
  return query select rec.id,rec.exception_id,rec.idempotency_key,rec.replay_number,rec.failure_class;
end;
$$;

create or replace function public.finish_exception_replay(
  p_organization_id uuid, p_replay_request_id uuid, p_worker_id text,
  p_outcome text, p_result_code text
) returns table(replay_request_id uuid, status text)
language plpgsql security definer set search_path = public, pg_temp as $$
declare rec public.exception_replay_requests; next_status text; audit_action text;
begin
  if p_outcome not in ('SUCCEEDED','FAILED_DEFINITE','OUTCOME_UNKNOWN') then raise exception 'unsupported dispatch outcome'; end if;
  if p_result_code is null or length(trim(p_result_code)) not between 1 and 80 then raise exception 'generic result code required'; end if;
  select * into rec from public.exception_replay_requests r where r.organization_id=p_organization_id and r.id=p_replay_request_id for update;
  if not found then raise exception 'replay request not found'; end if;
  if rec.status <> 'DISPATCHING' or rec.dispatch_worker_id <> p_worker_id or rec.dispatch_lease_until < now() then raise exception 'dispatch lease is not owned or has expired'; end if;
  next_status := case p_outcome when 'SUCCEEDED' then 'EXECUTED' when 'FAILED_DEFINITE' then 'FAILED' else 'RECONCILIATION_REQUIRED' end;
  audit_action := case p_outcome when 'SUCCEEDED' then 'DISPATCH_SUCCEEDED' when 'FAILED_DEFINITE' then 'DISPATCH_FAILED' else 'RECONCILIATION_REQUIRED' end;
  update public.exception_replay_requests set status=next_status, finished_at=now(), result_code=trim(p_result_code),
    dispatch_lease_until=null where id=rec.id;
  insert into public.exception_replay_audit(organization_id,replay_request_id,actor_user_id,action,note)
    values(p_organization_id,rec.id,rec.approved_by,audit_action,trim(p_result_code));
  return query select rec.id,next_status;
end;
$$;

-- Expired dispatch leases may represent an already-applied external action. Never replay them automatically.
create or replace function public.reconcile_expired_exception_replays(p_cutoff interval default interval '2 minutes')
returns integer language plpgsql security definer set search_path = public, pg_temp as $$
declare changed integer;
begin
  if p_cutoff < interval '30 seconds' or p_cutoff > interval '1 day' then raise exception 'cutoff outside safe bounds'; end if;
  with stale as (
    update public.exception_replay_requests r set status='RECONCILIATION_REQUIRED', finished_at=now(),
      dispatch_lease_until=null, result_code='WORKER_LEASE_EXPIRED'
    where r.status='DISPATCHING' and r.dispatch_lease_until < now()-p_cutoff
    returning r.organization_id,r.id,r.approved_by
  )
  insert into public.exception_replay_audit(organization_id,replay_request_id,actor_user_id,action,note)
    select organization_id,id,approved_by,'RECONCILIATION_REQUIRED','Dispatch lease expired; external outcome must be reconciled' from stale;
  get diagnostics changed = row_count;
  return changed;
end;
$$;

revoke all on function public.claim_exception_replay(uuid,uuid,text,integer) from public, anon, authenticated;
revoke all on function public.finish_exception_replay(uuid,uuid,text,text,text) from public, anon, authenticated;
revoke all on function public.reconcile_expired_exception_replays(interval) from public, anon, authenticated;
grant execute on function public.claim_exception_replay(uuid,uuid,text,integer) to service_role;
grant execute on function public.finish_exception_replay(uuid,uuid,text,text,text) to service_role;
grant execute on function public.reconcile_expired_exception_replays(interval) to service_role;
