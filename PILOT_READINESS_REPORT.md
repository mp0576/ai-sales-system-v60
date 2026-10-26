# MVP v28 — Pilot Readiness Report

**Release decision: BLOCKED for live customer traffic.** This package is a staging candidate, not a production-authorized release.

## Evidence available in this release

| Area | Evidence | Status | What this does not prove |
|---|---|---|---|
| Application logic | Local automated tests | Locally verified | Production load, hosted dependencies, or external provider behavior |
| Python source | `compileall` | Locally verified | Runtime configuration correctness |
| SQL migration inventory | Static migration manifest and ordering checks | Locally verified | Migrations execute successfully on hosted Postgres |
| RPC compatibility | `scripts/check_rpc_contracts.py` | Locally verified | Actual deployed function definitions/grants match |
| RLS and SQL privileges | `sql/staging_security_matrix.sql` | Query prepared; remote evidence pending | Tenant isolation has not been proven against real accounts |
| Worker recovery | Fake repositories and failure-injection tests | Application behavior locally tested | Real multi-connection locking and lease behavior |
| Provider idempotency/reconciliation | Provider-neutral policy tests | Policy locally tested | Provider-specific lookup, idempotency, or sandbox behavior |
| Dashboard authentication | Configuration gate and code-level checks | Partially checked locally | Full external security assessment or browser-level penetration test |

## Mandatory blockers before pilot

- [ ] Apply migrations `0001`–`0018` to a dedicated, disposable Supabase/Postgres staging project.
- [ ] Run `sql/staging_contract_check.sql` and `sql/staging_security_matrix.sql`; retain timestamped output.
- [ ] Create two organizations and real test accounts for OWNER, ADMIN, MANAGER, MEMBER, and VIEWER.
- [ ] Demonstrate cross-tenant reads and writes are denied for every critical table and RPC.
- [ ] Test approval authorization and audit trail for each sensitive action.
- [ ] Run concurrent outbox, idempotency, and webhook-claim tests using separate database connections.
- [ ] Exercise provider sandbox success, rejection, rate-limit, timeout-after-acceptance, and reconciliation paths.
- [ ] Verify secrets are stored only in server-side secret management and absent from browser bundles/logs.
- [ ] Run backup/restore and operational alerting checks.
- [ ] Obtain explicit owner sign-off after reviewing evidence and rollback procedure.

## Safe initial pilot configuration

- `OUTBOUND_ENABLED=false`
- `ENABLE_LIVE_PAYMENTS=false`
- Use provider sandbox credentials only.
- Use a dedicated staging tenant with synthetic or explicitly consented test data.
- Keep human approval enabled for discounts beyond policy, refunds beyond configured limit, custom contracts, legal matters, and strategic accounts.
- Enable live outbound only after the mandatory blockers above are closed and an owner explicitly approves the change.

## Suggested acceptance criteria

1. No cross-tenant access in a repeatable role-by-tenant test matrix.
2. No duplicate external side effect after retry/timeout simulations where provider idempotency is available.
3. Ambiguous provider outcomes reconcile from authoritative provider state or are escalated; never assume a timeout means failure.
4. All critical actions have tenant identity, actor/worker identity, idempotency key, outcome, and audit trace.
5. Alerts exist for dead-letter growth, repeated retries, lease expiry, webhook backlog, payment mismatch, and approval backlog.
6. Rollback and disable-switch procedures are exercised, not merely documented.

## Evidence collection record

Record each run with: date/time (UTC), Git/archive SHA-256, staging project identifier (never keys), migration version, test account roles, command/query, result, and operator. Do not paste access tokens, service-role keys, customer messages, or payment data into this report.

## Current decision

**NO-GO for live commercial automation.** Local tests and static checks are necessary but insufficient. Proceed only to controlled staging validation until all mandatory blockers have evidence and sign-off.
