# v33 — Durable Exception Center

## Data model

- `operational_exceptions`: current tenant-scoped state and assignment.
- `operational_exception_audit`: append-only transition history written in the same transaction as each change.
- Unique key `(organization_id, source_type, source_id)` makes ingestion idempotent without merging events across organizations.

## Operations

- `create_operational_exception`: validates bounds, inserts once, and returns the existing record for a duplicate source event.
- `transition_operational_exception`: takes a row lock, rechecks the actor's organization membership and role in SQL, verifies assignees belong to the same organization, prevents changes to terminal records, and commits state plus audit atomically.
- The two RPCs are executable only by `service_role`; the authenticated API must derive actor identity from its verified session, never from an untrusted request field.

## Apply and verify in staging

1. Back up the disposable staging database and apply migrations in numeric order through `0019_durable_exception_center.sql`.
2. Run `python scripts/check_rpc_contracts.py` and `python scripts/release_gate.py --static-only` locally.
3. As a database administrator, verify RLS is enabled on both tables, client roles have no direct privileges, and only `service_role` has RPC execute permission.
4. Test with two real staging organizations: duplicate creation within one organization returns the same record; the same source identity in another organization creates a separate record; cross-tenant transitions, non-manager roles, and cross-tenant assignees fail; valid transitions create exactly one audit row.
5. Confirm audit history and exception state survive process restart and concurrent transition attempts.

## Limitations

This release has not been applied to a live Supabase instance. Local tests mock the PostgREST repository and do not prove PostgreSQL execution, deployed grants, RLS, or multi-process concurrency. Keep outbound messaging and payments disabled until those checks pass.
