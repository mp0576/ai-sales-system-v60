# v37 — Controlled replay dispatch

The v37 layer connects the v36 approval ledger to an injected backend executor. The SQL `claim_exception_replay` RPC atomically locks a tenant-scoped request with `FOR UPDATE SKIP LOCKED`, verifies it is approved, rechecks the exception state, and creates a short worker lease. Only a successful claim is passed to the executor. The executor receives the original idempotency key and a minimal command, not the raw database row.

`finish_exception_replay` checks tenant, worker ownership, status, and lease expiry before recording a generic result code and audit event. Outcomes are `EXECUTED`, `FAILED`, or `RECONCILIATION_REQUIRED`. An exception thrown by the executor, invalid executor output, or failure to persist the finish result is treated as ambiguous; the dispatcher does not retry in-process.

## Crash and delivery semantics

This is **at-least-once**, not exactly-once. A worker can crash after the provider applies an action but before the database records completion. The original provider idempotency key must be used for every provider call. Expired `DISPATCHING` requests are never automatically re-claimed: `reconcile_expired_exception_replays` moves sufficiently stale leases to `RECONCILIATION_REQUIRED`, because the external result may already have happened. Run this recovery RPC from a trusted scheduler and review the resulting queue before any further action.

## Operational safeguards

- Apply migrations through `0021_controlled_replay_dispatch.sql` in a disposable Supabase staging project first.
- The executor must be a trusted backend adapter with provider-specific idempotency support; do not wire arbitrary user-supplied callbacks or payloads.
- Never use this path for unknown provider outcomes, payment reconciliation, invalid webhook signatures, or exceptions requiring human approval.
- Live outbound messaging and live payments remain disabled by default.
- The local tests use fake stores and executors. They do not prove deployed SQL behavior, provider idempotency, tenant isolation, or a successful end-to-end staging run.

## Staging acceptance

1. Verify RPC signatures and grants with `python scripts/check_rpc_contracts.py` and `sql/staging_contract_check.sql`.
2. With two staging tenants, prove one tenant cannot claim, inspect, or finish another tenant's request.
3. Run two workers against the same approved request and confirm only one receives a claim.
4. Simulate executor timeout after provider-side acceptance; confirm the same idempotency key is preserved and the request is reconciled rather than blindly repeated.
5. Kill a worker after claim, wait for lease expiry, run the stale-lease reconciler, and confirm no automatic redispatch occurs.
6. Verify audit rows for request, approval, claim, finish, and reconciliation.
