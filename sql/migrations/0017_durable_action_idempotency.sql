-- v22: durable idempotency arbitration shared by all API and worker processes.
-- Provider calls are not performed inside these RPCs/transactions.
create table if not exists public.action_idempotency (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  action_type text not null check (action_type in ('message','email','calendar','checkout')),
  idempotency_key text not null check (length(idempotency_key) between 1 and 200),
  status text not null default 'IN_PROGRESS'
    check (status in ('IN_PROGRESS','SUCCEEDED','FINAL_FAILURE','RETRYABLE')),
  result jsonb,
  lease_owner text,
  lease_until timestamptz,
  attempts integer not null default 1 check (attempts >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, action_type, idempotency_key)
);

create index if not exists action_idempotency_stale_lease_idx
  on public.action_idempotency (lease_until) where status = 'IN_PROGRESS';

alter table public.action_idempotency enable row level security;
revoke all on table public.action_idempotency from public, anon, authenticated;
grant select, insert, update, delete on table public.action_idempotency to service_role;

create or replace function public.claim_action_idempotency(
  p_organization_id uuid,
  p_action_type text,
  p_idempotency_key text,
  p_worker_id text,
  p_lease_seconds integer default 120
) returns table(decision text, result jsonb)
language plpgsql security definer set search_path = public, pg_temp as $$
declare
  rec public.action_idempotency;
  inserted boolean := false;
begin
  if p_organization_id is null then raise exception 'organization required'; end if;
  if p_action_type not in ('message','email','calendar','checkout') then raise exception 'invalid action type'; end if;
  if p_idempotency_key is null or length(trim(p_idempotency_key)) < 1 or length(p_idempotency_key) > 200 then raise exception 'invalid idempotency key'; end if;
  if p_worker_id is null or length(trim(p_worker_id)) < 1 or length(p_worker_id) > 200 then raise exception 'invalid worker id'; end if;
  if p_lease_seconds is null or p_lease_seconds < 15 or p_lease_seconds > 3600 then raise exception 'invalid lease duration'; end if;

  insert into public.action_idempotency(organization_id, action_type, idempotency_key, lease_owner, lease_until)
  values (p_organization_id, p_action_type, p_idempotency_key, p_worker_id, now() + make_interval(secs => p_lease_seconds))
  on conflict (organization_id, action_type, idempotency_key) do nothing
  returning true into inserted;
  if not found then inserted := false; end if;

  select * into rec from public.action_idempotency i
   where i.organization_id = p_organization_id
     and i.action_type = p_action_type
     and i.idempotency_key = p_idempotency_key
   for update;

  if rec.status in ('SUCCEEDED','FINAL_FAILURE') then
    return query select 'REPLAY'::text, rec.result;
    return;
  end if;
  if not inserted and rec.status = 'IN_PROGRESS' and rec.lease_until > now() then
    return query select 'BUSY'::text, null::jsonb;
    return;
  end if;
  -- Same worker retries, RETRYABLE results, and expired leases may claim the operation.
  update public.action_idempotency i
     set status = 'IN_PROGRESS', lease_owner = p_worker_id,
         lease_until = now() + make_interval(secs => p_lease_seconds),
         attempts = case when rec.status = 'IN_PROGRESS' and rec.lease_owner = p_worker_id then rec.attempts else rec.attempts + 1 end,
         updated_at = now()
   where i.id = rec.id;
  return query select 'EXECUTE'::text, null::jsonb;
end;
$$;

create or replace function public.finish_action_idempotency(
  p_organization_id uuid,
  p_action_type text,
  p_idempotency_key text,
  p_worker_id text,
  p_result jsonb,
  p_retryable boolean default false
) returns table(status text)
language plpgsql security definer set search_path = public, pg_temp as $$
declare
  rec public.action_idempotency;
  new_status text;
begin
  if p_organization_id is null or p_worker_id is null or length(trim(p_worker_id)) < 1 then raise exception 'tenant and worker required'; end if;
  if p_action_type not in ('message','email','calendar','checkout') then raise exception 'invalid action type'; end if;
  if p_idempotency_key is null or length(trim(p_idempotency_key)) < 1 or length(p_idempotency_key) > 200 then raise exception 'invalid idempotency key'; end if;
  if p_result is null or jsonb_typeof(p_result) <> 'object' then raise exception 'result object required'; end if;
  select * into rec from public.action_idempotency i
   where i.organization_id = p_organization_id and i.action_type = p_action_type
     and i.idempotency_key = p_idempotency_key for update;
  if not found or rec.status <> 'IN_PROGRESS' or rec.lease_owner <> p_worker_id or rec.lease_until <= now() then
    raise exception 'idempotency lease ownership mismatch';
  end if;
  new_status := case when p_retryable then 'RETRYABLE'
                     when coalesce((p_result->>'ok')::boolean, false) then 'SUCCEEDED'
                     else 'FINAL_FAILURE' end;
  update public.action_idempotency i
     set status = new_status, result = p_result,
         lease_owner = null, lease_until = null, updated_at = now()
   where i.id = rec.id;
  return query select new_status;
end;
$$;

revoke all on function public.claim_action_idempotency(uuid,text,text,text,integer) from public, anon, authenticated;
revoke all on function public.finish_action_idempotency(uuid,text,text,text,jsonb,boolean) from public, anon, authenticated;
grant execute on function public.claim_action_idempotency(uuid,text,text,text,integer) to service_role;
grant execute on function public.finish_action_idempotency(uuid,text,text,text,jsonb,boolean) to service_role;
