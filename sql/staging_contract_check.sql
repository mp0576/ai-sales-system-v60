-- v25 read-only checks for a dedicated Supabase staging database.
-- Run in the SQL editor as an administrator. This performs SELECTs only.
-- A PASS means the expected objects/privileges are present, not that every RLS policy is correct.

with expected(name, signature) as (
  values
    ('claim_action_idempotency', 'public.claim_action_idempotency(uuid,text,text,text,integer)'),
    ('finish_action_idempotency', 'public.finish_action_idempotency(uuid,text,text,text,jsonb,boolean)'),
    ('claim_provider_webhook', 'public.claim_provider_webhook(uuid,text,text,text,integer,timestamp with time zone,text)'),
    ('finish_provider_webhook', 'public.finish_provider_webhook(uuid,text,text,text,boolean,text)'),
    ('claim_outbox', 'public.claim_outbox(integer,text,integer)'),
    ('finish_outbox', 'public.finish_outbox(uuid,uuid,text,boolean,text,integer,boolean)'),
    ('create_operational_exception', 'public.create_operational_exception(uuid,text,text,text,text,text)'),
    ('transition_operational_exception', 'public.transition_operational_exception(uuid,uuid,uuid,text,uuid,text)'),
    ('request_exception_replay', 'public.request_exception_replay(uuid,uuid,uuid,integer,text,text,text,text)'),
    ('decide_exception_replay', 'public.decide_exception_replay(uuid,uuid,uuid,boolean,text)'),
    ('claim_exception_replay', 'public.claim_exception_replay(uuid,uuid,text,integer)'),
    ('finish_exception_replay', 'public.finish_exception_replay(uuid,uuid,text,text,text)'),
    ('reconcile_expired_exception_replays', 'public.reconcile_expired_exception_replays(interval)')
), functions as (
  select e.name, e.signature, to_regprocedure(e.signature) as proc_oid
  from expected e
)
select 'function_exists' as check_type, name as object_name,
       case when proc_oid is not null then 'PASS' else 'FAIL' end as result,
       signature as detail
from functions
union all
select 'rls_enabled', c.relname,
       case when c.relrowsecurity then 'PASS' else 'FAIL' end,
       'public.' || c.relname
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname in ('action_idempotency', 'provider_webhook_inbox', 'outbox_events', 'operational_exceptions', 'operational_exception_audit', 'exception_replay_requests', 'exception_replay_audit')
union all
select 'service_role_execute', f.name,
       case when has_function_privilege('service_role', f.proc_oid, 'EXECUTE') then 'PASS' else 'FAIL' end,
       f.signature
from functions f where f.proc_oid is not null
union all
select 'client_execute_revoked', f.name,
       case when not has_function_privilege('anon', f.proc_oid, 'EXECUTE')
                  and not has_function_privilege('authenticated', f.proc_oid, 'EXECUTE')
            then 'PASS' else 'FAIL' end,
       f.signature
from functions f where f.proc_oid is not null
order by 1, 2;
