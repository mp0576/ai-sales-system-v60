# MVP v42 — expired replay lease recovery

## Purpose

v42 exposes the existing PostgreSQL `reconcile_expired_exception_replays(interval)` RPC through the trusted backend repository and adds an explicit staging-only maintenance command. Stale `DISPATCHING` records are moved to `RECONCILIATION_REQUIRED` with an audit entry. They are **not** returned to `APPROVED` and are never automatically dispatched again, because a crashed worker may have already caused an external side effect.

## Dry run

```bash
python scripts/reconcile_expired_replays.py
```

This is a no-op and does not connect to Supabase.

## Explicit staging execution

Set `APP_ENV=staging`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` in the trusted backend environment, then run:

```bash
APP_ENV=staging python scripts/reconcile_expired_replays.py --execute --cutoff-seconds 120
```

This performs a database write through a service-role RPC. Use a dedicated staging project and review the affected stale leases first. The default grace period is 120 seconds; allowed range is 30–86400 seconds. The command prints only a count and never prints credentials or database error bodies.

## Safety invariants

- No `--execute`: no network request and no mutation.
- `APP_ENV` must be exactly `staging`; production and unspecified environments are blocked.
- The RPC moves stale dispatches to reconciliation, not back to the queue.
- The operation is audited by the SQL function and restricted to `service_role`.
- Unknown external outcomes still require provider-side reconciliation before any new approved replay request is created.

## Evidence boundary

Local tests cover argument validation, RPC request construction, response parsing, error redaction, and static SQL invariants. They do not execute PostgreSQL, prove live role grants/RLS, or validate an external provider sandbox. Apply and verify migrations in staging before relying on this operation.
