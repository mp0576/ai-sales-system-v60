# Release checklist — v14

## Local/pilot release
- [ ] `python -m pytest -q` passes.
- [ ] `python scripts/preflight.py` passes with a newly generated secret.
- [ ] No real credentials or `.env` files in the archive/repository.
- [ ] `/health` responds after startup.
- [ ] Protected API returns 401 without a token and 503 if token configuration is missing.
- [ ] Port is loopback-bound unless an approved proxy/identity layer is present.
- [ ] Outbound messaging and live payments remain disabled.
- [ ] Operator knows the service uses synthetic in-memory demo data.

## Production release — NOT CLEARED
- [ ] Durable Supabase/Postgres repositories integrated and migration plan reviewed.
- [ ] Authenticated per-user identity, organization membership and role authorization.
- [ ] RLS cross-tenant tests run against staging.
- [ ] Durable audit trail and approval execution/resume flow.
- [ ] Real sandbox end-to-end tests for messaging, calendar, email and payments.
- [ ] Consent/DNC legal review and provider policy review.
- [ ] Monitoring, alerting, backup/restore and incident-response drills.
- [ ] Security review, dependency scanning, load test and rollback rehearsal.
- [ ] Explicit sign-off by accountable operator.


## v15 Supabase dashboard validation (staging only)
- [ ] Apply `0013_dashboard_persistence.sql` after prior migrations in a disposable staging project.
- [ ] Test expired/invalid access tokens, non-member tenant access, member reads, member approval denial, and manager/owner approval resolution.
- [ ] Confirm approval state update and audit insertion commit or roll back together.
- [ ] Confirm PostgREST calls use the caller JWT and never the service-role key.
- [ ] Confirm demo token is rejected when `APP_ENV=production`.
- [ ] Do not enable live outbound, payment processing, or real-customer onboarding; overall release gate remains closed.


## v19 RLS/privilege hardening — staging gate
- [ ] Apply migrations 0001–0016 in order to a disposable Supabase staging project.
- [ ] Use two users that each belong only to their own distinct organization; run `scripts/staging_tenant_isolation.py`.
- [ ] Verify a normal authenticated user cannot insert/update actions or events, read/write outbox rows, call worker RPCs, or forge audit rows.
- [ ] Verify OWNER/ADMIN/MANAGER can resolve a pending approval only within their organization, and MEMBER/VIEWER cannot.
- [ ] Verify the approval state update and audit row are atomic and duplicate resolution is rejected.
- [ ] Review grants on all SECURITY DEFINER functions; no production clearance until live staging evidence is attached.

## v20 release gate
- [ ] `python scripts/release_gate.py --static-only` passes.
- [ ] Configure a dedicated Supabase staging project using a trusted shell.
- [ ] Run `python scripts/release_gate.py` with live outbound and payments disabled.
- [ ] Apply and review migrations on staging in the documented order.
- [ ] Run `scripts/staging_smoke.py` and `scripts/staging_tenant_isolation.py` with staging identities.
- [ ] Verify RPC grants, worker queue behavior, retries, lease expiry and duplicate event handling against staging.
- [ ] Run each provider's sandbox tests; verify signed webhooks and idempotency.
- [ ] Keep production traffic disabled until every blocking item above has recorded evidence.


## v23 webhook staging blockers
- [ ] Apply migration `0018_provider_webhook_inbox.sql` to disposable staging after `0017`.
- [ ] Confirm only `service_role` can execute inbox RPCs; verify anon/authenticated calls fail.
- [ ] Run simultaneous duplicate-event claims from two independent database sessions; exactly one must receive `PROCESS`, the other `BUSY` or `REPLAY`.
- [ ] Simulate worker termination, lease expiry, and retryable completion.
- [ ] Verify provider signatures before any inbox claim.
- [ ] Confirm webhook payloads and secrets are not persisted in inbox rows or logs.
- [ ] Test Stripe payment event types individually; do not drop distinct financial events based only on timestamps.
