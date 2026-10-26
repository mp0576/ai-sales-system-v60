# Migration order

Apply SQL migrations in numeric order in a disposable Supabase staging project first:

1. `0001_core.sql`
2. `0002_rls.sql`
3. `0003_outbox_claim.sql`
4. `0004_worker_runtime.sql`
5. `0011_dashboard.sql`
6. `0012_customer_lifecycle.sql`
7. `0013_dashboard_persistence.sql`
8. `0014_runtime_persistence.sql`
9. `0015_permanent_outbox_failures.sql`
10. `0016_rls_privilege_hardening.sql`
11. `0017_durable_action_idempotency.sql`
12. `0018_provider_webhook_inbox.sql`
13. `0019_durable_exception_center.sql`
14. `0020_audited_replay_approvals.sql`
15. `0021_controlled_replay_dispatch.sql`
16. `0022_real_estate_lead_persistence.sql`
17. `0023_operational_lead_api.sql`

Use the Supabase SQL editor or the project's migration workflow. Back up any non-empty
project before applying migrations. Do not run migrations directly against production
until the schema diff and rollback/restore plan have been reviewed.

The `SupabaseRuntimeRepository` uses `SUPABASE_SERVICE_ROLE_KEY` from a trusted backend
only. It bypasses RLS by design; the repository therefore requires explicit tenant IDs,
validates tenant ownership in RPCs, and never returns provider response bodies in errors.
The service role key must not be placed in the dashboard, browser, public workflow input,
Git, or logs. n8n should call a backend endpoint or receive narrowly scoped task payloads,
not receive the service role secret.

## Staging smoke check (v18)

After applying migrations to a dedicated staging project, run the read-only connectivity
check from a trusted backend shell:

```bash
APP_ENV=staging python scripts/staging_smoke.py
```

Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the shell or a local untracked `.env`
loader. The script makes only two GET requests: Auth health and an `organizations` table
metadata/data request with `limit=0`. It performs no writes and does not prove tenant RLS,
RPC grants, webhook signatures, or end-to-end provider behavior. It explicitly refuses
`APP_ENV=production`.
Migration `0016` hardens the client/server boundary: authenticated users can read tenant-scoped event/action history but cannot directly mutate actions or the worker outbox; approval decisions must use the role-checked atomic RPC; worker claim and runtime mutation RPCs are service-role only. Review this migration on a disposable staging project before applying it to any environment with existing data.

## Two-user tenant-isolation probe (v19)

Create two staging users, each belonging only to its own distinct organization and provide their access JWTs and organization IDs in a trusted shell. The probe performs GET requests only; it checks both unfiltered RLS results and explicit cross-tenant queries.

```bash
APP_ENV=staging \
SUPABASE_URL='https://YOUR-PROJECT.supabase.co' \
SUPABASE_ANON_KEY='YOUR_PUBLIC_ANON_KEY' \
STAGING_USER_A_JWT='USER_A_ACCESS_TOKEN' STAGING_USER_A_ORG_ID='UUID_A' \
STAGING_USER_B_JWT='USER_B_ACCESS_TOKEN' STAGING_USER_B_ORG_ID='UUID_B' \
python scripts/staging_tenant_isolation.py
```

Use only a dedicated staging project and short-lived user access tokens. Do not use the service-role key for this probe: the purpose is to exercise end-user RLS. This read-only probe is useful evidence, not a complete penetration test or production certification.


## Durable action idempotency (v22)

Migration `0017_durable_action_idempotency.sql` adds a server-only, tenant-scoped idempotency table and two RPCs. `claim_action_idempotency` atomically arbitrates ownership with a lease; `finish_action_idempotency` persists a safe provider result only if the caller still owns a valid lease. Only `service_role` can execute these RPCs. Apply and verify this migration in a disposable staging project before use. The table stores result metadata and provider IDs; do not put message bodies, credentials, or payment secrets in `result`. External calls are outside database transactions and still require provider-side idempotency to cover ambiguous network timeouts.


## Provider webhook inbox (v23)

Migration `0018_provider_webhook_inbox.sql` adds a server-only inbox keyed by organization, provider, and provider event ID. Verify the provider signature before claiming an event. Claim/finish RPCs use row locks and leases to avoid concurrent duplicate processing and permit recovery after a lease expires. Store only event identifiers and short error codes, not raw payloads or secrets. Timestamp ordering is appropriate only for provider object-state snapshots; do not discard distinct financial ledger events merely because their timestamps are older. The RPCs have not been certified against a live staging database until the staging checks are run.


## RPC contract verification (v25)

Before staging, run `python scripts/check_rpc_contracts.py`. This static check compares the latest SQL function definitions in migration order with the Python RPC argument contracts and checks service-role grants/client-role revocations for worker RPCs. It is also included in `scripts/release_gate.py --static-only`.

For a real staging database, execute `sql/staging_contract_check.sql` as an administrator. It performs read-only catalog checks for function presence, RLS enablement on key tables, and execute privileges. Review every row: any `FAIL` blocks rollout. This query checks deployed catalog state, but does not prove full transaction semantics or end-to-end RLS isolation; keep running `scripts/staging_tenant_isolation.py` with two dedicated staging users.


## Staging security evidence (v27)

Run `sql/staging_security_matrix.sql` to review RLS state, effective table privileges, and grants for sensitive runtime RPCs. This is a read-only report, not a substitute for testing real tenant and role behavior. See `SECURITY.md` and run the two-tenant probe with actual staging users.


## Durable exception center (v33)

Migration `0019_durable_exception_center.sql` adds a tenant-scoped operational exception table with a unique `(organization_id, source_type, source_id)` key and an append-only transition audit timeline. `create_operational_exception` is idempotent for a source event. `transition_operational_exception` locks the exception row, checks that the actor has an OWNER/ADMIN/MANAGER membership in that same organization, validates assignees against that organization, and records state change plus audit row in one database transaction. The RPCs are service-role-only; the backend must authenticate the user and pass the verified user UUID, and the SQL rechecks membership. Never accept actor IDs or organization IDs directly from an untrusted client without deriving/validating them in the authenticated API layer. Apply and verify on disposable staging before use; this repository has not been tested against a live Supabase project.

### v34 worker integration note

No additional migration is required for v34: the worker uses the tenant/source unique key and `create_operational_exception` RPC introduced by `0019_durable_exception_center.sql`. Apply migrations through `0019` in staging first. Test that a dead-letter write followed by an exception RPC outage remains visible as a dead letter and is surfaced in worker metrics; replaying exception creation must deduplicate by `(organization_id, source_type, source_id)`.

## v36 — audited exception replay approvals

The v36 migration stores tenant-scoped replay requests and append-only decision audit rows. It validates allowlisted transient classes, a confirmed `NOT_APPLIED` outcome, the original idempotency key, replay budget and exception state. Approval requires a different manager than the requester. Approval only records a decision; it does not enqueue or dispatch work. Apply and verify this migration in staging before using it.

### v37 — controlled replay dispatch

Migration `0021_controlled_replay_dispatch.sql` adds atomic claiming, short worker leases, a guarded finish RPC, and stale-lease reconciliation. Only approved requests can be claimed; the exception is revalidated under lock. A stale dispatch is moved to `RECONCILIATION_REQUIRED`, never auto-claimed again, because a provider action may already have succeeded. Provider calls remain outside database transactions and require the original provider idempotency key. This migration has not been validated against a live Supabase staging project in this release.

## v38 staging acceptance pack

After applying migrations through `0021_controlled_replay_dispatch.sql` to a dedicated staging project, run `sql/staging_replay_dispatch_acceptance.sql` in the SQL editor as an administrator. It performs catalog-only SELECTs and checks replay RPC signatures, grants, client-role revocations, RLS flags, dispatch columns, atomic claim locking, and stale-lease reconciliation. Export its result grid as CSV with columns `check_name,result,detail`, then run `python scripts/verify_staging_acceptance.py exported-results.csv`. The evaluator fails closed on any failed, missing, duplicated, or partial result. Neither a passing catalog report nor the local test suite proves live tenant isolation, concurrency, or provider idempotency; execute the rehearsal in `STAGING_REPLAY_ACCEPTANCE_V38.md` before any pilot decision.


## v49 real-estate lead persistence

Migration `0022_real_estate_lead_persistence.sql` adds tenant-keyed lead snapshots, request idempotency records and append-only lead events. All three tables have RLS enabled and direct client-role privileges revoked; only trusted `service_role` access is granted. Since `service_role` bypasses RLS, the application backend must derive and validate the organization from authenticated membership rather than trusting browser or workflow input. The event log intentionally stores event metadata and a payload digest; review the snapshot payload before persisting personal data. The local SQLite adapter is for development and rehearsal only, not a multi-host production database. Apply and test the migration on dedicated staging before production consideration.


## v51 operational lead API

Migration `0023_operational_lead_api.sql` adds a caller-JWT/RLS-facing lead snapshot store and an atomic authenticated RPC. The write function is `SECURITY DEFINER` only to support atomic writes while direct client writes are revoked; it checks `auth.uid()` membership and uses a fixed search path. Audit the function and validate grants/RLS in staging before deployment.


## v52 concurrent lead writes

Migration `0024_operational_lead_concurrency.sql` replaces the v51 write RPC with transaction-scoped advisory locks, acquired in a stable order for `(organization, idempotency key)` and `(organization, lead)`. This closes the first-write race where `SELECT ... FOR UPDATE` cannot lock a snapshot row that does not yet exist. Apply after `0023_operational_lead_api.sql`; inspect function grants and run the dedicated staging concurrency probe before relying on this remotely.
