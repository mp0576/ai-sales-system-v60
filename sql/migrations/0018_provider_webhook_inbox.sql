-- v23: durable provider webhook inbox. Verify provider signatures before claiming events.
-- Distinct financial ledger events must all be processed; timestamp ordering is for state snapshots only.
create table if not exists public.provider_webhook_inbox (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  provider text not null check (length(provider) between 1 and 40),
  event_id text not null check (length(event_id) between 1 and 250),
  object_id text,
  provider_created_at timestamptz,
  status text not null default 'IN_PROGRESS'
    check (status in ('IN_PROGRESS','PROCESSED','RETRYABLE','FAILED')),
  lease_owner text,
  lease_until timestamptz,
  attempts integer not null default 1 check (attempts >= 1),
  error_code text check (error_code is null or length(error_code) <= 80),
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (organization_id, provider, event_id)
);
create index if not exists provider_webhook_inbox_stale_idx
  on public.provider_webhook_inbox (lease_until) where status = 'IN_PROGRESS';
create index if not exists provider_webhook_inbox_object_time_idx
  on public.provider_webhook_inbox (organization_id, provider, object_id, provider_created_at);

alter table public.provider_webhook_inbox enable row level security;
revoke all on table public.provider_webhook_inbox from public, anon, authenticated;
grant select, insert, update, delete on table public.provider_webhook_inbox to service_role;

create or replace function public.claim_provider_webhook(
  p_organization_id uuid, p_provider text, p_event_id text, p_worker_id text,
  p_lease_seconds integer default 120, p_provider_created_at timestamptz default null,
  p_object_id text default null
) returns table(decision text)
language plpgsql security definer set search_path = public, pg_temp as $$
declare rec public.provider_webhook_inbox; inserted boolean := false;
begin
  if p_organization_id is null then raise exception 'organization required'; end if;
  if p_provider is null or length(trim(p_provider)) not between 1 and 40 then raise exception 'invalid provider'; end if;
  if p_event_id is null or length(trim(p_event_id)) not between 1 and 250 then raise exception 'invalid event id'; end if;
  if p_worker_id is null or length(trim(p_worker_id)) not between 1 and 200 then raise exception 'invalid worker id'; end if;
  if p_lease_seconds is null or p_lease_seconds < 15 or p_lease_seconds > 3600 then raise exception 'invalid lease duration'; end if;
  insert into public.provider_webhook_inbox(organization_id, provider, event_id, object_id, provider_created_at, lease_owner, lease_until)
  values (p_organization_id, p_provider, p_event_id, p_object_id, p_provider_created_at, p_worker_id,
          now() + make_interval(secs => p_lease_seconds))
  on conflict (organization_id, provider, event_id) do nothing returning true into inserted;
  if not found then inserted := false; end if;
  select * into rec from public.provider_webhook_inbox w
   where w.organization_id = p_organization_id and w.provider = p_provider and w.event_id = p_event_id for update;
  if rec.status = 'PROCESSED' then return query select 'REPLAY'::text; return; end if;
  if not inserted and rec.status = 'IN_PROGRESS' and rec.lease_until > now() then
    return query select 'BUSY'::text; return;
  end if;
  update public.provider_webhook_inbox w
    set status = 'IN_PROGRESS', lease_owner = p_worker_id,
        lease_until = now() + make_interval(secs => p_lease_seconds),
        attempts = case when rec.lease_owner = p_worker_id then rec.attempts else rec.attempts + 1 end,
        error_code = null, updated_at = now()
    where w.id = rec.id;
  return query select 'PROCESS'::text;
end;
$$;

create or replace function public.finish_provider_webhook(
  p_organization_id uuid, p_provider text, p_event_id text, p_worker_id text,
  p_succeeded boolean, p_error_code text default null
) returns table(status text)
language plpgsql security definer set search_path = public, pg_temp as $$
declare rec public.provider_webhook_inbox; new_status text;
begin
  if p_organization_id is null or p_worker_id is null or length(trim(p_worker_id)) not between 1 and 200 then raise exception 'tenant and worker required'; end if;
  if p_provider is null or length(trim(p_provider)) not between 1 and 40 then raise exception 'invalid provider'; end if;
  if p_event_id is null or length(trim(p_event_id)) not between 1 and 250 then raise exception 'invalid event id'; end if;
  select * into rec from public.provider_webhook_inbox w
   where w.organization_id = p_organization_id and w.provider = p_provider and w.event_id = p_event_id for update;
  if not found or rec.status <> 'IN_PROGRESS' or rec.lease_owner <> p_worker_id or rec.lease_until <= now() then
    raise exception 'webhook lease ownership mismatch';
  end if;
  new_status := case when p_succeeded then 'PROCESSED' else 'RETRYABLE' end;
  update public.provider_webhook_inbox w set status = new_status,
    lease_owner = null, lease_until = null,
    error_code = case when p_succeeded then null else left(coalesce(p_error_code, 'PROCESSING_FAILED'), 80) end,
    processed_at = case when p_succeeded then now() else null end, updated_at = now()
    where w.id = rec.id;
  return query select new_status;
end;
$$;
revoke all on function public.claim_provider_webhook(uuid,text,text,text,integer,timestamptz,text) from public, anon, authenticated;
revoke all on function public.finish_provider_webhook(uuid,text,text,text,boolean,text) from public, anon, authenticated;
grant execute on function public.claim_provider_webhook(uuid,text,text,text,integer,timestamptz,text) to service_role;
grant execute on function public.finish_provider_webhook(uuid,text,text,text,boolean,text) to service_role;
