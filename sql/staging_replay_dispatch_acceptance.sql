-- v38 read-only acceptance probe for migrations 0020-0021.
-- Run in the Supabase SQL editor as an administrator on a DISPOSABLE STAGING project.
-- SELECT-only: it does not create test tenants, requests, or provider actions.
-- PASS proves catalog shape/grants only; concurrency and provider behavior require the separate runbook.
with expected_functions(name, signature) as (
  values
    ('request_exception_replay', 'public.request_exception_replay(uuid,uuid,uuid,integer,text,text,text,text)'),
    ('decide_exception_replay', 'public.decide_exception_replay(uuid,uuid,uuid,boolean,text)'),
    ('claim_exception_replay', 'public.claim_exception_replay(uuid,uuid,text,integer)'),
    ('finish_exception_replay', 'public.finish_exception_replay(uuid,uuid,text,text,text)'),
    ('reconcile_expired_exception_replays', 'public.reconcile_expired_exception_replays(interval)')
), resolved as (
  select name, signature, to_regprocedure(signature) as oid from expected_functions
), checks as (
  select 'rpc_exists:' || name as check_name,
         case when oid is not null then 'PASS' else 'FAIL' end as result,
         signature as detail from resolved
  union all
  select 'service_role_execute:' || name,
         case when oid is not null and has_function_privilege('service_role', oid, 'EXECUTE') then 'PASS' else 'FAIL' end,
         signature from resolved
  union all
  select 'client_execute_revoked:' || name,
         case when oid is not null and not has_function_privilege('anon', oid, 'EXECUTE')
              and not has_function_privilege('authenticated', oid, 'EXECUTE') then 'PASS' else 'FAIL' end,
         signature from resolved
  union all
  select 'rls_enabled:' || t.table_name,
         case when c.oid is not null and c.relrowsecurity then 'PASS' else 'FAIL' end,
         'public.' || t.table_name
  from (values ('exception_replay_requests'), ('exception_replay_audit'), ('operational_exceptions')) t(table_name)
  left join pg_namespace n on n.nspname='public'
  left join pg_class c on c.relnamespace=n.oid and c.relname=t.table_name
  union all
  select 'dispatch_columns:' || col.column_name,
         case when exists (
           select 1 from information_schema.columns c
           where c.table_schema='public' and c.table_name='exception_replay_requests'
             and c.column_name=col.column_name
         ) then 'PASS' else 'FAIL' end,
         'public.exception_replay_requests.' || col.column_name
  from (values ('dispatch_worker_id'), ('dispatch_lease_until'), ('finished_at'), ('result_code'), ('idempotency_key'), ('replay_number')) col(column_name)
  union all
  select 'atomic_claim_locking',
         case when position('for update skip locked' in lower(pg_get_functiondef(to_regprocedure('public.claim_exception_replay(uuid,uuid,text,integer)')))) > 0 then 'PASS' else 'FAIL' end,
         'claim RPC uses FOR UPDATE SKIP LOCKED'
  union all
  select 'expired_lease_reconciliation_only',
         case when position('reconciliation_required' in lower(pg_get_functiondef(to_regprocedure('public.reconcile_expired_exception_replays(interval)')))) > 0
                and position('approved' in lower(pg_get_functiondef(to_regprocedure('public.reconcile_expired_exception_replays(interval)')))) = 0
              then 'PASS' else 'FAIL' end,
         'expired dispatch leases are routed to reconciliation, not approval/dispatch'
  union all
  select 'claim_rpc_security_definer_search_path',
         case when p.prosecdef and coalesce(array_to_string(p.proconfig, ','), '') like '%search_path=public, pg_temp%'
              then 'PASS' else 'FAIL' end,
         'claim RPC is SECURITY DEFINER with fixed search_path'
  from pg_proc p where p.oid=to_regprocedure('public.claim_exception_replay(uuid,uuid,text,integer)')
)
select check_name, result, detail from checks order by check_name;
