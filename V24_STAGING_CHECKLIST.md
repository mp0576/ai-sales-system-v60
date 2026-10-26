# v24 Staging Validation Checklist

This checklist is intentionally explicit about the difference between local contract tests and live infrastructure evidence.

## Before running
- [ ] Use a disposable Supabase project, not production.
- [ ] Set `APP_ENV=staging`.
- [ ] Keep `OUTBOUND_ENABLED=false` and `ENABLE_LIVE_PAYMENTS=false`.
- [ ] Configure secrets in the runtime environment, never in the ZIP or Git.
- [ ] Take a database snapshot or confirm the project contains no production data.

## Database and tenant boundaries
- [ ] Apply migrations `0001` through `0018` in documented order.
- [ ] Verify each migration succeeds on a clean database.
- [ ] Create two organizations and users with OWNER, MANAGER, MEMBER and VIEWER roles.
- [ ] Confirm cross-tenant reads and writes are denied.
- [ ] Confirm authenticated users cannot call service-role worker RPCs.
- [ ] Confirm service-role key is only present in backend/worker environment.

## Worker / outbox
- [ ] Enqueue one test event using the transactional RPC.
- [ ] Run two independent worker processes concurrently; confirm one lease owner per row.
- [ ] Kill a worker after claim; confirm lease expiry and safe reclaim.
- [ ] Inject a transient handler failure; confirm retry schedule and bounded attempts.
- [ ] Inject a permanent failure; confirm dead-letter and no hot retry loop.
- [ ] Force lease expiry before completion; confirm stale worker cannot finish the row.
- [ ] Verify logs exclude event payloads, access tokens, and provider response bodies.

## Webhook inbox and providers
- [ ] Verify provider webhook signature before inbox claim.
- [ ] Deliver the same event ID twice; confirm one effective state transition.
- [ ] Deliver events out of order; confirm stale snapshots do not overwrite newer state.
- [ ] Do not discard distinct payment ledger events based only on timestamps.
- [ ] Use provider sandbox and stable idempotency keys for checkout/message requests.
- [ ] Simulate timeout after provider acceptance; reconcile by provider idempotency key or lookup before retry.

## Evidence to retain
- [ ] Migration logs and migration versions.
- [ ] Sanitized test report and worker summaries.
- [ ] RLS test results for each role and tenant.
- [ ] Provider sandbox request/event IDs (no secrets or customer content).
- [ ] Release-gate output and final go/no-go decision.

A passing local test suite is not a substitute for completing this checklist. Live outbound and live payments remain disabled until all blocking items are passed and reviewed.
