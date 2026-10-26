create or replace function public.save_operational_lead_snapshot(
 p_organization_id uuid, p_lead_id text, p_state text, p_payload jsonb,
 p_event_type text, p_idempotency_key text, p_expected_version bigint default null
) returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_existing operational_lead_idempotency%rowtype;
 v_current operational_lead_snapshots%rowtype; v_version bigint; v_digest text; v_now timestamptz := now();
begin
 if auth.uid() is null then raise insufficient_privilege using message='authentication required'; end if;
 if not exists(select 1 from organization_members m where m.organization_id=p_organization_id and m.user_id=auth.uid()) then
   raise insufficient_privilege using message='organization membership required';
 end if;
 if p_lead_id is null or length(trim(p_lead_id)) not between 1 and 250 or p_state is null or length(trim(p_state)) not between 1 and 80
    or p_idempotency_key is null or length(trim(p_idempotency_key)) not between 8 and 250
    or p_payload is null or jsonb_typeof(p_payload) <> 'object' then
   raise check_violation using message='invalid lead snapshot input';
 end if;
 v_digest := encode(digest(convert_to(jsonb_build_object('lead_id',p_lead_id,'state',p_state,'payload',p_payload,'event_type',p_event_type,'expected_version',p_expected_version)::text,'UTF8'),'sha256'),'hex');
 -- Serialize identical idempotency keys, including the first insert when no row exists.
 perform pg_advisory_xact_lock(hashtextextended(p_organization_id::text || ':idem:' || p_idempotency_key, 0));
 -- Serialize writes to a lead even when its snapshot has not been created yet.
 -- All callers acquire idempotency lock before lead lock to keep lock order stable.
 perform pg_advisory_xact_lock(hashtextextended(p_organization_id::text || ':lead:' || p_lead_id, 0));
 select * into v_existing from operational_lead_idempotency where organization_id=p_organization_id and idempotency_key=p_idempotency_key for update;
 if found then
   if v_existing.request_digest <> v_digest then raise unique_violation using message='idempotency key reused with different request'; end if;
   select * into v_current from operational_lead_snapshots where organization_id=p_organization_id and lead_id=v_existing.lead_id;
   return jsonb_build_object('duplicate',true,'version',v_existing.resulting_version,'lead',to_jsonb(v_current));
 end if;
 select * into v_current from operational_lead_snapshots where organization_id=p_organization_id and lead_id=p_lead_id for update;
 if not found then
   if p_expected_version is not null and p_expected_version <> 0 then raise serialization_failure using message='version conflict'; end if;
   v_version := 1;
   insert into operational_lead_snapshots(organization_id,lead_id,state,payload,version,created_at,updated_at)
    values(p_organization_id,p_lead_id,p_state,p_payload,v_version,v_now,v_now);
 else
   if p_expected_version is not null and p_expected_version <> v_current.version then raise serialization_failure using message='version conflict'; end if;
   v_version := v_current.version + 1;
   update operational_lead_snapshots set state=p_state,payload=p_payload,version=v_version,updated_at=v_now
    where organization_id=p_organization_id and lead_id=p_lead_id;
 end if;
 insert into operational_lead_events(organization_id,lead_id,event_type,event_payload,created_at)
 values(p_organization_id,p_lead_id,coalesce(nullif(p_event_type,''),'LEAD_SNAPSHOT_SAVED'),
  jsonb_build_object('state',p_state,'version',v_version,'payload_digest',encode(digest(convert_to(p_payload::text,'UTF8'),'sha256'),'hex'),
  'idempotency_key_digest',encode(digest(convert_to(p_idempotency_key,'UTF8'),'sha256'),'hex')),v_now);
 insert into operational_lead_idempotency(organization_id,idempotency_key,request_digest,lead_id,resulting_version,created_at)
 values(p_organization_id,p_idempotency_key,v_digest,p_lead_id,v_version,v_now);
 select * into v_current from operational_lead_snapshots where organization_id=p_organization_id and lead_id=p_lead_id;
 return jsonb_build_object('duplicate',false,'version',v_version,'lead',to_jsonb(v_current));
end $$;
revoke all on function public.save_operational_lead_snapshot(uuid,text,text,jsonb,text,text,bigint) from public, anon;
grant execute on function public.save_operational_lead_snapshot(uuid,text,text,jsonb,text,text,bigint) to authenticated;
