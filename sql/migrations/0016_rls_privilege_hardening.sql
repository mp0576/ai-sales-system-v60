-- v19 security hardening: client identities must not manipulate worker queues,
-- action execution records, or fabricate audit history. Runtime RPCs are service-role only.

-- The RLS helper is callable by authenticated clients because policies invoke it;
-- avoid exposing it to anonymous callers.
revoke all on function public.is_org_member(uuid) from public, anon;
grant execute on function public.is_org_member(uuid) to authenticated, service_role;

-- Keep tenant-visible business history read-only to normal authenticated users.
drop policy if exists events_tenant_all on public.events;
create policy events_member_select on public.events
  for select to authenticated using (public.is_org_member(organization_id));

drop policy if exists actions_tenant_all on public.actions;
create policy actions_member_select on public.actions
  for select to authenticated using (public.is_org_member(organization_id));

-- No authenticated/anon policies on outbox_events: worker queue is backend-only.
drop policy if exists outbox_tenant_all on public.outbox_events;

-- Approval decisions must go through the atomic RPC so role checks and audit logging
-- cannot be bypassed by a direct REST update.
drop policy if exists approval_manager_update on public.approval_requests;
drop policy if exists dashboard_audit_member_insert on public.dashboard_audit_events;

create or replace function public.resolve_dashboard_approval(
  p_organization_id uuid,
  p_approval_id uuid,
  p_approved boolean,
  p_reason text
) returns setof public.approval_requests
language plpgsql security definer set search_path = public, pg_temp as $$
declare
  resolved public.approval_requests;
  actor uuid := auth.uid();
begin
  if actor is null then
    raise exception 'authenticated user required' using errcode = '42501';
  end if;
  if length(trim(coalesce(p_reason, ''))) < 3 or length(p_reason) > 1000 then
    raise exception 'decision reason must contain 3 to 1000 characters';
  end if;
  if not exists (
    select 1 from public.organization_members m
    where m.organization_id = p_organization_id
      and m.user_id = actor
      and upper(m.role) in ('OWNER', 'ADMIN', 'MANAGER')
  ) then
    raise exception 'manager role required for this organization' using errcode = '42501';
  end if;

  update public.approval_requests
     set status = case when p_approved then 'APPROVED' else 'REJECTED' end,
         resolved_at = now(), resolved_by = actor,
         resolution_reason = trim(p_reason), updated_at = now()
   where id = p_approval_id
     and organization_id = p_organization_id
     and status = 'PENDING'
   returning * into resolved;

  if not found then
    return;
  end if;

  insert into public.dashboard_audit_events
    (organization_id, actor_user_id, event_type, target_type, target_id, reason)
  values
    (p_organization_id, actor,
     case when p_approved then 'APPROVAL_APPROVED' else 'APPROVAL_REJECTED' end,
     'approval_request', p_approval_id::text, trim(p_reason));
  return next resolved;
end;
$$;

-- SECURITY DEFINER is safe here because the function performs explicit auth.uid(),
-- membership, role, tenant and status checks. Do not expose it to anon/public.
revoke all on function public.resolve_dashboard_approval(uuid, uuid, boolean, text) from public, anon;
grant execute on function public.resolve_dashboard_approval(uuid, uuid, boolean, text) to authenticated;

-- Worker queue functions are backend-only. Restrict claim RPC and validate bounds.
create or replace function public.claim_outbox(batch_size integer, worker_id text, lease_seconds integer default 120)
returns setof public.outbox_events
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if batch_size is null or batch_size < 1 or batch_size > 100 then
    raise exception 'batch_size must be between 1 and 100';
  end if;
  if worker_id is null or length(trim(worker_id)) < 1 or length(worker_id) > 200 then
    raise exception 'worker_id must contain 1 to 200 characters';
  end if;
  if lease_seconds is null or lease_seconds < 10 or lease_seconds > 3600 then
    raise exception 'lease_seconds must be between 10 and 3600';
  end if;
  return query
  with candidates as (
    select o.id from public.outbox_events o
    where (o.status = 'PENDING' and o.available_at <= now())
       or (o.status = 'PROCESSING' and o.locked_at < now() - make_interval(secs => lease_seconds))
    order by o.available_at, o.created_at
    for update skip locked limit batch_size
  )
  update public.outbox_events o
     set status = 'PROCESSING', locked_at = now(), locked_by = worker_id, attempts = attempts + 1
   where o.id in (select id from candidates)
  returning o.*;
end;
$$;
revoke all on function public.claim_outbox(integer, text, integer) from public, anon, authenticated;
grant execute on function public.claim_outbox(integer, text, integer) to service_role;

-- Ensure worker mutation RPCs cannot be called with an end-user JWT.
revoke all on function public.create_lead_with_event(uuid, text, uuid, jsonb, jsonb, text) from public, anon, authenticated;
revoke all on function public.append_event_to_outbox(uuid, text, jsonb, uuid, text, text) from public, anon, authenticated;
revoke all on function public.finish_outbox(uuid, uuid, text, boolean, text, integer, boolean) from public, anon, authenticated;
grant execute on function public.create_lead_with_event(uuid, text, uuid, jsonb, jsonb, text) to service_role;
grant execute on function public.append_event_to_outbox(uuid, text, jsonb, uuid, text, text) to service_role;
grant execute on function public.finish_outbox(uuid, uuid, text, boolean, text, integer, boolean) to service_role;
