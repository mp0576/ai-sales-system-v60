# Deployment and release guide

## Release classification

**MVP v15 adds a production-authenticated dashboard data path, but the overall product remains pilot-only.** In `APP_ENV=production`, dashboard API requests are authenticated through Supabase Auth, tenant membership is verified against `organization_members`, and data requests use the caller's access token so PostgreSQL RLS remains active. Demo mode continues to use a synthetic in-memory store. The wider sales, lifecycle, worker and provider flows are not yet wired end-to-end to durable repositories; do not onboard paying customers or process real customer data until all release blockers below are closed.

## Local demo
1. Generate a unique `DASHBOARD_API_TOKEN` (at least 32 random characters) and keep it out of Git.
2. Install `requirements-dashboard.txt` and run `python scripts/preflight.py`.
3. Start `uvicorn app.dashboard.api:app --host 127.0.0.1 --port 8000`.
4. Open the dashboard, enter the token and `org_demo`, and load the demo data.

## Supabase dashboard integration (staging only)
1. Create a dedicated Supabase staging project and enable Supabase Auth.
2. Apply migrations in order: `0001_core.sql`, `0002_rls.sql`, `0003_outbox_claim.sql`, `0004_worker_runtime.sql`, `0011_dashboard.sql`, `0012_customer_lifecycle.sql`, `0013_dashboard_persistence.sql`. Review the target schema and test the policies first.
3. Configure `SUPABASE_URL` and `SUPABASE_ANON_KEY` on the server only. Do not put the service-role key in the browser or this dashboard repository.
4. Set `APP_ENV=production` for the dashboard API. The browser's token field must contain a valid Supabase user access token, not `DASHBOARD_API_TOKEN`.
5. Ensure the user belongs to the requested organization. Read queries use the user's JWT and RLS. Approval resolution requires `OWNER`, `ADMIN` or `MANAGER` and uses `resolve_dashboard_approval` to update the approval and write the audit event in one database transaction.
6. Verify member access, cross-tenant denial, manager/owner approval, member approval denial, expired/invalid sessions and RLS directly in staging.
7. Note: the global `scripts/preflight.py` deliberately rejects production mode because the overall automation product is not production-cleared, even though this dashboard-auth path exists. Do not bypass that release gate to enable live sales automation.

## Required before whole-product production
- Connect lead/event/action/lifecycle services and workers to durable repositories and transactional outbox.
- Add usage-cost persistence; until then the dashboard reports AI cost as `0.0` rather than inventing a value.
- Wire durable provider outcomes, OAuth/token refresh, verified webhook reconciliation and retry/duplicate handling end-to-end.
- Test migrations and RLS in a real staging project with member, manager, owner and cross-tenant accounts.
- Add MFA for administrators, session controls, rate limiting, security headers, secret rotation, monitoring/alerting, backups and restore drills.
- Verify consent provenance, DNC propagation, privacy/retention/deletion requirements and local legal requirements for outreach.
- Run load, penetration, dependency and data protection reviews; test incident response and rollback.
- Separate development/staging/production and assign an accountable human for exception handling.

## Rollback
1. Stop deployments and disable outbound automation at application and provider layers.
2. Roll back to the last immutable image tag.
3. Preserve audit/payment/webhook evidence.
4. Reconcile provider-side messages/payments before resuming workers.
5. Record the incident, root cause, affected tenants and recovery verification.
