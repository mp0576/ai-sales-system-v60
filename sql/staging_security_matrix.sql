-- Read-only security evidence query. Run as a database administrator on disposable staging.
-- It reports RLS state and effective table privileges; it does not mutate data.
with critical_tables(table_name) as (
  values ('organizations'), ('organization_members'), ('leads'), ('contacts'),
         ('conversations'), ('messages'), ('actions'), ('events'), ('outbox_events'),
         ('approval_requests'), ('audit_logs'), ('payment_events'),
         ('operational_exceptions'), ('operational_exception_audit'), ('exception_replay_requests'), ('exception_replay_audit')
),
rls as (
  select c.table_name, coalesce(pc.relrowsecurity, false) as rls_enabled,
         coalesce(pc.relforcerowsecurity, false) as rls_forced
  from critical_tables c
  left join pg_namespace pn on pn.nspname = 'public'
  left join pg_class pc on pc.relnamespace = pn.oid and pc.relname = c.table_name
),
privileges as (
  select c.table_name,
         has_table_privilege('anon', 'public.' || c.table_name, 'SELECT') as anon_select,
         has_table_privilege('authenticated', 'public.' || c.table_name, 'SELECT') as authenticated_select,
         has_table_privilege('authenticated', 'public.' || c.table_name, 'INSERT') as authenticated_insert,
         has_table_privilege('authenticated', 'public.' || c.table_name, 'UPDATE') as authenticated_update,
         has_table_privilege('authenticated', 'public.' || c.table_name, 'DELETE') as authenticated_delete
  from critical_tables c
)
select r.table_name, r.rls_enabled, r.rls_forced,
       p.anon_select, p.authenticated_select, p.authenticated_insert,
       p.authenticated_update, p.authenticated_delete,
       case when r.table_name is null then 'BLOCK'
            when not r.rls_enabled then 'BLOCK: RLS DISABLED'
            when r.table_name in ('actions','events','outbox_events','approval_requests','audit_logs','payment_events')
              and (p.authenticated_insert or p.authenticated_update or p.authenticated_delete)
              then 'REVIEW: DIRECT MUTATION GRANT'
            else 'REVIEW POLICIES AND MEMBERSHIP MATRIX' end as assessment
from rls r join privileges p using (table_name)
order by r.table_name;

-- Inspect grants for security-sensitive RPCs. Expected: worker RPCs service_role only;
-- approval resolution authenticated only (function validates role and tenant internally).
select p.proname as function_name, grantee.rolname as grantee, privilege_type
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
cross join lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
join pg_roles grantee on grantee.oid = a.grantee
where n.nspname = 'public'
  and p.proname in ('claim_outbox', 'finish_outbox', 'claim_action_idempotency',
                    'finish_action_idempotency', 'claim_provider_webhook',
                    'finish_provider_webhook', 'resolve_dashboard_approval',
                    'create_operational_exception', 'transition_operational_exception',
                    'request_exception_replay', 'decide_exception_replay', 'claim_exception_replay',
                    'finish_exception_replay', 'reconcile_expired_exception_replays')
order by p.proname, grantee.rolname, privilege_type;
