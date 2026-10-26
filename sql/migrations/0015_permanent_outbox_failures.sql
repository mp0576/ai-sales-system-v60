-- Extend outbox completion so deterministic/policy failures can be dead-lettered immediately.
-- Drop the old signature so PostgREST has one unambiguous RPC overload.
drop function if exists public.finish_outbox(uuid,uuid,text,boolean,text,integer);

create or replace function public.finish_outbox(
  p_organization_id uuid, p_outbox_id uuid, p_worker_id text, p_succeeded boolean,
  p_error text default '', p_retry_delay_seconds integer default 30, p_permanent boolean default false
) returns setof outbox_events
language plpgsql security invoker set search_path = public as $$
begin
  return query update outbox_events o
    set status=case when p_succeeded then 'DONE' when p_permanent or o.attempts >= 5 then 'FAILED' else 'PENDING' end,
        available_at=case when not p_succeeded and not p_permanent and o.attempts < 5 then now()+make_interval(secs=>greatest(1,least(p_retry_delay_seconds,86400))) else o.available_at end,
        last_error=case when p_succeeded then null else left(coalesce(p_error,'worker failed'),1000) end,
        completed_at=case when p_succeeded then now() else o.completed_at end,
        dead_lettered_at=case when not p_succeeded and (p_permanent or o.attempts >= 5) then now() else o.dead_lettered_at end,
        locked_at=null, locked_by=null
    where o.id=p_outbox_id and o.organization_id=p_organization_id and o.status='PROCESSING' and o.locked_by=p_worker_id
    returning o.*;
end; $$;

revoke all on function public.finish_outbox(uuid,uuid,text,boolean,text,integer,boolean) from public, anon, authenticated;
grant execute on function public.finish_outbox(uuid,uuid,text,boolean,text,integer,boolean) to service_role;
