-- Durable runtime RPCs. All multi-table state changes happen in one DB transaction.
-- These functions are SECURITY INVOKER. Backend workers use the server-only service role;
-- never expose that key to a browser or an n8n workflow payload.

create or replace function public.create_lead_with_event(
  p_organization_id uuid, p_state text, p_contact_id uuid, p_facts jsonb,
  p_metadata jsonb, p_idempotency_key text
) returns table(lead_id uuid, event_id uuid, outbox_id uuid, duplicate boolean)
language plpgsql security invoker set search_path = public as $$
declare v_lead leads; v_event events; v_outbox outbox_events;
begin
  if p_idempotency_key is null or length(trim(p_idempotency_key)) < 1 or length(p_idempotency_key) > 200 then
    raise exception 'invalid idempotency key';
  end if;
  select e.* into v_event from events e where e.organization_id=p_organization_id and e.idempotency_key=p_idempotency_key;
  if found then
    select l.* into v_lead from leads l where l.id=v_event.lead_id and l.organization_id=p_organization_id;
    select o.* into v_outbox from outbox_events o where o.event_id=v_event.id and o.organization_id=p_organization_id;
    return query select v_lead.id, v_event.id, v_outbox.id, true; return;
  end if;
  if p_contact_id is not null and not exists(select 1 from contacts c where c.id=p_contact_id and c.organization_id=p_organization_id) then
    raise exception 'contact does not belong to organization';
  end if;
  insert into leads(organization_id,contact_id,state,facts,metadata)
  values(p_organization_id,p_contact_id,coalesce(nullif(p_state,''),'NEW'),coalesce(p_facts,'{}'::jsonb),coalesce(p_metadata,'{}'::jsonb)) returning * into v_lead;
  insert into events(organization_id,type,lead_id,payload,idempotency_key)
  values(p_organization_id,'LEAD_CREATED',v_lead.id,jsonb_build_object('state',v_lead.state),p_idempotency_key) returning * into v_event;
  insert into outbox_events(organization_id,event_id,topic,payload)
  values(p_organization_id,v_event.id,'lead.created',jsonb_build_object('lead_id',v_lead.id,'state',v_lead.state)) returning * into v_outbox;
  return query select v_lead.id, v_event.id, v_outbox.id, false;
end; $$;

create or replace function public.append_event_to_outbox(
  p_organization_id uuid, p_event_type text, p_payload jsonb, p_lead_id uuid,
  p_idempotency_key text, p_topic text
) returns table(event_id uuid, outbox_id uuid, duplicate boolean)
language plpgsql security invoker set search_path = public as $$
declare v_event events; v_outbox outbox_events;
begin
  if p_idempotency_key is null or length(trim(p_idempotency_key)) < 1 or length(p_idempotency_key) > 200 then raise exception 'invalid idempotency key'; end if;
  if p_event_type is null or length(trim(p_event_type)) < 1 then raise exception 'event type required'; end if;
  if p_lead_id is not null and not exists(select 1 from leads l where l.id=p_lead_id and l.organization_id=p_organization_id) then raise exception 'lead does not belong to organization'; end if;
  select e.* into v_event from events e where e.organization_id=p_organization_id and e.idempotency_key=p_idempotency_key;
  if found then
    select o.* into v_outbox from outbox_events o where o.event_id=v_event.id and o.organization_id=p_organization_id;
    return query select v_event.id, v_outbox.id, true; return;
  end if;
  insert into events(organization_id,type,lead_id,payload,idempotency_key)
  values(p_organization_id,p_event_type,p_lead_id,coalesce(p_payload,'{}'::jsonb),p_idempotency_key)
  on conflict(organization_id,idempotency_key) do nothing returning * into v_event;
  if v_event.id is null then
    select e.* into v_event from events e where e.organization_id=p_organization_id and e.idempotency_key=p_idempotency_key;
    select o.* into v_outbox from outbox_events o where o.event_id=v_event.id and o.organization_id=p_organization_id;
    return query select v_event.id, v_outbox.id, true; return;
  end if;
  insert into outbox_events(organization_id,event_id,topic,payload)
  values(p_organization_id,v_event.id,coalesce(nullif(p_topic,''),lower(p_event_type)),coalesce(p_payload,'{}'::jsonb)) returning * into v_outbox;
  return query select v_event.id, v_outbox.id, false;
end; $$;

create or replace function public.finish_outbox(
  p_organization_id uuid, p_outbox_id uuid, p_worker_id text, p_succeeded boolean,
  p_error text default '', p_retry_delay_seconds integer default 30
) returns setof outbox_events
language plpgsql security invoker set search_path = public as $$
begin
  return query update outbox_events o
    set status=case when p_succeeded then 'DONE' when o.attempts >= 5 then 'FAILED' else 'PENDING' end,
        available_at=case when not p_succeeded and o.attempts < 5 then now()+make_interval(secs=>greatest(1,least(p_retry_delay_seconds,86400))) else o.available_at end,
        last_error=case when p_succeeded then null else left(coalesce(p_error,'worker failed'),1000) end,
        completed_at=case when p_succeeded then now() else o.completed_at end,
        dead_lettered_at=case when not p_succeeded and o.attempts >= 5 then now() else o.dead_lettered_at end,
        locked_at=null, locked_by=null
    where o.id=p_outbox_id and o.organization_id=p_organization_id and o.status='PROCESSING' and o.locked_by=p_worker_id
    returning o.*;
end; $$;

-- Service role bypasses RLS by design; authenticated users do not receive EXECUTE grants here.
revoke all on function public.create_lead_with_event(uuid,text,uuid,jsonb,jsonb,text) from public, anon, authenticated;
revoke all on function public.append_event_to_outbox(uuid,text,jsonb,uuid,text,text) from public, anon, authenticated;
revoke all on function public.finish_outbox(uuid,uuid,text,boolean,text,integer) from public, anon, authenticated;
grant execute on function public.create_lead_with_event(uuid,text,uuid,jsonb,jsonb,text) to service_role;
grant execute on function public.append_event_to_outbox(uuid,text,jsonb,uuid,text,text) to service_role;
grant execute on function public.finish_outbox(uuid,uuid,text,boolean,text,integer) to service_role;
