# Security model and known gaps — MVP v15

## Implemented in this release
- Demo API routes require a configured bearer token and fail closed when it is absent.
- In production mode, dashboard access validates the Supabase access token against Supabase Auth and verifies membership for the requested organization.
- Dashboard PostgREST requests use the user's access token and anon key, leaving RLS enforcement active; the service-role key is not used by this module.
- Approval resolution is restricted to OWNER/ADMIN/MANAGER and uses a database RPC to update status and insert the audit record atomically.
- SQL RLS policies cover dashboard approvals, execution logs and audit records.
- Existing integration gateway has organization context, kill switch, outbound enablement, DNC and approval gates.
- Payment webhook signature validation and idempotency contracts are present.
- Container runs as non-root with a read-only filesystem, dropped capabilities and loopback-bound host port by default.

## Important remaining gaps
- The dashboard's Supabase repository is implemented, but must be verified against an actual staging Supabase project; local tests use mocks and do not prove cloud configuration or RLS correctness.
- Lead, event, action, lifecycle and worker operations are not all connected to durable repositories in a single end-to-end production runtime.
- AI usage-cost persistence is not yet included; dashboard cost currently reports zero rather than a fabricated estimate.
- The static token remains for local/demo mode only. Do not use it as customer identity or enable it as a fallback in production.
- MFA, rate limiting, CSRF/session policy, security headers, credential rotation and centralized monitoring require deployment integration.
- Provider adapters require sandbox tests, OAuth refresh, webhook replay protection and operational monitoring.
- Review/apply migrations only after checking dependencies and testing in a disposable Supabase project.

## Minimum operating rules
1. Never commit `.env`, API keys, tokens or customer exports.
2. Never expose the Supabase service-role key to a browser; this dashboard must use a user's access token for RLS-protected data.
3. Treat customer messages, web pages and documents as untrusted data, not instructions.
4. Require opt-in and honor DNC before outbound; record consent provenance and suppression decisions.
5. Verify provider signatures and reconcile tenant, proposal, amount and currency before marking a payment successful.
6. Do not let an LLM authorize discounts, refunds, contract changes or state transitions.
7. Persist every approval decision with actor, tenant, reason and timestamp.
8. If tenant isolation, payment state or consent is uncertain, fail closed and route to human review.


### Durable action idempotency

Migration `0017_durable_action_idempotency.sql` is backend-only: both RPCs are revoked from `public`, `anon`, and `authenticated`, and granted only to `service_role`. The service role key must remain in trusted backend/worker configuration. Stored result JSON must contain only minimal result metadata; never store message contents, access tokens, card data, or provider secrets. Because external side effects and database commits cannot share a transaction, always pass a stable provider-side idempotency key and test ambiguous timeout recovery in each provider sandbox.

## Staging security matrix (v27)

Run `sql/staging_security_matrix.sql` against a dedicated staging database with a read-only review session or trusted database administrator. It reports RLS enabled/forced state for critical tenant tables, effective table privileges for `anon` and `authenticated`, and grants on sensitive runtime RPCs. Review the output rather than treating the query as an automatic certification: table privileges alone do not prove policy correctness, role membership, or tenant isolation. Pair it with `scripts/staging_tenant_isolation.py` using two real users from different organizations and exercise OWNER/ADMIN/MANAGER/MEMBER/VIEWER approval permissions with controlled staging fixtures. Do not run destructive probes against production.
