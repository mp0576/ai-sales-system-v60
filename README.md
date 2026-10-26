# Latest release: MVP v54

The current iteration adds a signed staging release decision. It requires both a valid HMAC-SHA256 integrity envelope and a fresh, semantically valid v53 acceptance report. This is not proof that remote tests actually ran; staging remains uncertified until evidence is collected against the real staging project. See [STAGING_RELEASE_DECISION_V54.md](STAGING_RELEASE_DECISION_V54.md).

## Latest release: MVP v51\n\nThe current iteration adds a caller-JWT/RLS-backed Supabase lead repository for production mode and migration 0023. See [V51_HOSTED_LEAD_STORAGE.md](V51_HOSTED_LEAD_STORAGE.md). Local/pilot mode uses SQLite. No live Supabase or provider integration is certified.\n\n# AI Sales System — MVP v28

Multi-tenant sales automation pilot: durable worker runtime, Supabase persistence contracts, provider adapters, dashboard, and release checks.

## Guarantees
- bounded exponential retry/backoff
- permanent vs retryable failure distinction
- dead-letter after retry budget
- tenant and idempotency context carried into jobs
- provider calls kept outside database transactions
- n8n treated as execution/scheduling infrastructure, not the source of business truth

## Status
Staging candidate only, not a production deployment. Supabase and provider credentials are intentionally external. See `PILOT_READINESS_REPORT.md`; live commercial automation remains NO-GO until remote evidence and owner sign-off are complete.

## MVP v10 — Provider adapters and Internal Action Gateway

This release adds provider-neutral contracts for WhatsApp, Google Calendar,
Stripe Checkout and email; deterministic mock providers; HTTP adapters with
injected transports; retryable/non-retryable provider result classification;
Stripe webhook signature verification; and a policy-first gateway enforcing
organization scope, kill switch, outbound opt-in, DNC, and approval requirements.

**Safety defaults:** outbound messaging is disabled unless `outbound_enabled`
is explicitly true. Missing credentials produce a blocked result, not a simulated
success. A successful Stripe Checkout Session creation is not proof of payment;
only a verified provider webhook can mark a proposal paid. Never expose provider
secrets in the dashboard or workflow payloads. Provider calls must happen outside
DB transactions and their outcomes must be persisted with idempotency keys.

Production readiness notes:
- The Google Calendar adapter expects a valid OAuth access token; token refresh and
  OAuth consent flows belong in the deployment integration layer.
- The Stripe adapter uses a Stripe-specific `application/x-www-form-urlencoded`
  transport by default; injected transports are available for deterministic tests.
- Resend email adapter is available; verify sender domain and configure API credentials
  before enabling real sends.
- Run provider sandbox tests before enabling outbound actions for a tenant.

## MVP v11 — Dashboard + Exception Center

Adds an authenticated FastAPI dashboard API, a responsive CEO dashboard shell, a human approval queue, execution history, demo metrics, and a dashboard audit-event migration contract.

### Run locally

```bash
python -m pip install -r requirements-dashboard.txt
export DASHBOARD_API_TOKEN='replace-with-a-long-random-secret'
uvicorn app.dashboard.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`, enter the configured token and `org_demo`, then load the dashboard. `GET /health` is public; `/api/v1/*` fails closed if `DASHBOARD_API_TOKEN` is unset and requires a bearer token.

**Important boundary:** this dashboard currently uses an in-memory demo store, not the durable Supabase repositories. Metrics and executions are illustrative. The API filters demo records by organization, but a caller-supplied organization ID is not a production authorization boundary. Before exposing it to customers, replace the demo store with repositories that derive tenant membership from the authenticated identity, enforce role-based permissions and RLS, and write each approval decision to durable audit storage. Deploy only behind TLS and a proper identity provider; do not use a shared static bearer token as end-user authentication.

## MVP v12 — Customer Lifecycle + Retention

Adds deterministic lifecycle services for onboarding readiness, required integration checks, activation QA gates, customer health scoring, risk detection, renewal reminders and evidence-based upsell eligibility.

- Onboarding requires the eight configured business/profile fields and tested messaging, calendar and CRM integrations.
- Activation requires successful inbound messaging, AI response, CRM write, calendar booking, follow-up and audit-log checks.
- Health scoring validates component bounds and uses the configured 25/20/20/20/15 weighting.
- Risk rules detect inactivity over seven days, three or more automation failures in seven days, usage decline of at least 50%, and unresolved issues.
- Renewal reminder offsets default to 90/60/30/14/7 days; scheduling should be executed by the worker runtime with idempotency keys.
- Upsell is blocked until need is confirmed and value is demonstrated, and while a critical issue remains unresolved.
- SQL migration `0012_customer_lifecycle.sql` adds tenant-scoped lifecycle and idempotent lifecycle-event storage.

Rules are implemented and tested locally; production still requires wiring them to durable repositories, event/outbox publishing and scheduled workers.

## MVP v13 — End-to-end and failure-injection harness

Adds a deterministic Golden Path simulator for lead research, opt-in contact, qualification, offer, proposal, verified payment webhook, customer creation and activation. Failure cases cover missing opt-in, DNC, disabled outbound, provider retry, unverified research, tenant mismatch, custom contract/price-floor approval, invalid/duplicate webhooks, failed payments and activation QA.

Run all tests with `python -m pytest -q`. This is a local deterministic test harness, not a claim that external services or production deployment have been verified.

## MVP v14 — Deployment package and operational hardening

Includes a non-root Docker image, loopback-bound Compose configuration, read-only root filesystem, dropped capabilities, environment preflight checks, CI workflow, deployment guide, security model, operations runbook and release checklist.

**Release classification: local/pilot demo only.** The dashboard still uses synthetic in-memory data and a shared static token. Do not deploy as a public multi-tenant production service or enable live outbound/payment processing. Review `DEPLOY.md`, `SECURITY.md`, `OPERATIONS.md` and `RELEASE_CHECKLIST.md` before any deployment.


## MVP v15 — Supabase-authenticated dashboard path

Adds a Supabase Auth identity check, organization membership verification, and a PostgREST repository that uses the user's access token so RLS remains active. The dashboard can read tenant-scoped leads, events, lifecycle records, approvals and execution logs. Approval resolution is a single database RPC transaction that updates the approval and inserts its audit event.

Apply `sql/migrations/0013_dashboard_persistence.sql` after the existing migrations. Set `APP_ENV=production`, `SUPABASE_URL` and `SUPABASE_ANON_KEY` only in a staging environment while validating the dashboard path. In this mode, the browser token must be a Supabase user access token; the demo static token is not accepted.

**Important:** the whole automation product remains pilot-only. Other business/worker flows are not yet connected end-to-end to durable repositories, actual cloud RLS has not been verified by this local build, and live outbound/payment processing must remain disabled. `ai_cost_month_eur` is returned as zero until usage-cost persistence is implemented; do not interpret it as evidence that usage is free.

## MVP v16 — Durable runtime persistence

Adds `app/repositories/supabase_runtime.py` for server-side Supabase persistence of leads,
actions, events, and outbox tasks. Atomic multi-table writes use SQL RPC functions in
`sql/migrations/0014_runtime_persistence.sql`; worker claiming remains an atomic
`FOR UPDATE SKIP LOCKED` operation via the existing `claim_outbox` RPC. Idempotency keys
are scoped by organization. Outbox completion requires the active worker lease and tenant.

Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` only in the trusted backend
runtime. The service-role key bypasses RLS and must never reach browser code or n8n inputs.
Apply migrations in the order in `sql/MIGRATIONS.md`. Local tests mock the HTTP transport;
real Supabase staging verification is still required before production.

## MVP v17 — Durable Orchestrator + Worker service

Adds `app/orchestrator/runtime.py`, a tenant-bound event dispatcher with topic registry,
payload shape checks, stable event idempotency context, and explicit rejection of tenant
spoofing. `app/workers/durable_service.py` connects the dispatcher to the durable Supabase
outbox claim/finish RPCs. Success completes the lease; transient errors are rescheduled
with exponential backoff; policy/schema/unknown-topic failures are dead-lettered without
retries. Error records intentionally omit provider response bodies and payload content.

Migration `0015_permanent_outbox_failures.sql` adds an explicit permanent-failure flag to
the completion RPC. Apply after `0014_runtime_persistence.sql`. Handlers must still use the
provided stable idempotency key when calling external providers: a worker can crash after a
provider accepted a request but before the DB completion was committed, so delivery is
at-least-once, not magical exactly-once across external systems.

Run `python -m pytest -q` for the full local suite. Tests use fake repositories/providers;
run the documented Supabase staging checks before enabling any real customer or outbound
traffic. Outbound remains disabled by default.


### Supabase staging smoke check (v18)

Use a dedicated staging project only. Configure `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, and `APP_ENV=staging` in a trusted backend shell, then run:

```bash
python scripts/staging_smoke.py
```

This is a read-only connectivity check, not a certification of RLS or production readiness.
Never expose the service-role key in a browser, repository, or n8n payload.

## MVP v19 — RLS and privilege hardening

Adds migration `0016_rls_privilege_hardening.sql`: action/event history is read-only to authenticated client users, the worker outbox has no end-user RLS policy, approval decisions use a role-checked atomic RPC, audit rows cannot be forged through a direct client insert, and worker RPCs are restricted to `service_role`. The outbox claim RPC validates batch, worker and lease bounds.

Adds `scripts/staging_tenant_isolation.py`, a read-only two-user staging probe that checks organization visibility, unfiltered RLS results and explicit cross-organization queries. Configure two distinct staging users and run the command documented in `sql/MIGRATIONS.md`. Local tests validate the probe with mocked HTTP and statically inspect the migration; they do not prove a live Supabase project is configured correctly.

Apply migration `0016` after reviewing the existing policies in a disposable staging project. This remains a pilot release until the two-user probe, RPC grant checks, worker tests and provider sandbox flows pass against real services.

## MVP v20 — Fail-closed release gate

Adds `app/release/gate.py` and `scripts/release_gate.py` to check that the documented
SQL migrations are present and ordered, the v19 privilege guardrails remain visible,
example configuration does not enable live actions, no local `.env` files are included,
and staging configuration uses an HTTPS Supabase origin, distinct public/server keys,
a strong dashboard token, and disabled live outbound/payments.

Run repository-only checks with:

```bash
python scripts/release_gate.py --static-only
```

Run the full configuration gate in a trusted staging shell after setting `APP_ENV=staging`,
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and a unique
`DASHBOARD_API_TOKEN` of at least 32 characters:

```bash
python scripts/release_gate.py
```

The gate performs no network requests and no writes. Passing it is not proof that migrations
were applied, RLS/RPC grants work on the hosted database, workers survive real failures, or
provider sandbox tests passed. Live outbound and payments must remain disabled until those
separate checks have evidence.

## MVP v21 — safer retries and explicit payment enablement

The internal action gateway no longer caches transient (`retryable`) provider failures,
so the next worker attempt can recover. It still caches definitive outcomes within the
process; use provider idempotency and a durable database idempotency record for multi-worker
production. Checkout creation is now denied unless the trusted organization context has
`payments_enabled=True`. This flag defaults to false and must come from persisted server-side
organization settings, not a browser or webhook payload. Run `python -m pytest -q` for the
local suite; mocked success is not evidence of live provider readiness.


### Durable action idempotency (v22)

For multi-worker deployments, configure `SupabaseIdempotencyStore` on `InternalActionGateway` so action claims/results are arbitrated in Postgres rather than process memory. Apply migration `0017_durable_action_idempotency.sql` first. The local in-memory fallback is for tests/development only. See `sql/MIGRATIONS.md` and `SECURITY.md`; external provider idempotency is still required.


### v23 webhook processing
Apply `sql/migrations/0018_provider_webhook_inbox.sql` after migrations 0001–0017 in a disposable staging project. Verify each provider signature before calling `SupabaseWebhookInbox.claim`; then process the event and call `finish` with the same organization/provider/event/worker identity. Do not store raw webhook payloads in the inbox. The local tests do not replace live PostgreSQL race/lease tests.


## Release v23

This package adds a durable provider webhook inbox and recovery contract. Local validation: `python -m pytest -q` (141 passed) and `python scripts/release_gate.py --static-only`. These checks use simulated repositories for concurrency behavior and static inspection for SQL guardrails; they do not constitute a live PostgreSQL/Supabase staging test.


## v25 RPC contract verification

Run `python scripts/check_rpc_contracts.py` to compare the latest SQL RPC signatures with the Python callers and check worker RPC grants. Run `python scripts/release_gate.py --static-only` before packaging. For deployed staging checks, execute `sql/staging_contract_check.sql` in the Supabase SQL editor and use `scripts/staging_tenant_isolation.py` with two dedicated staging users. These checks do not replace end-to-end tests against a real staging instance.

## Validation in this package

- `pytest -q`: 164 passed (local automated tests).
- `python -m compileall -q app scripts tests`: passed.
- `python scripts/check_rpc_contracts.py`: 14/14 checks passed.
- `python scripts/release_gate.py --static-only`: passed.

No hosted Supabase instance or external provider sandbox was accessed for this release.

## Controlled pilot operations (v30)
Validate an agency-specific CSV before any separate import process:

```bash
python scripts/validate_pilot_leads.py templates/pilot_leads_template.csv --organization-id agency-demo
```

The command only validates; it does not persist leads or contact anyone. See `PILOT_OPERATIONS_V30.md` for consent safeguards, KPI definitions and pilot exit criteria.

### Current increment: v37 controlled replay dispatch

See `CONTROLLED_REPLAY_DISPATCH_V37.md` for atomic replay claiming, lease semantics, ambiguous-outcome handling, and staging acceptance. This release is locally validated only; no live Supabase or provider sandbox was exercised.


## v43 — Integridade das evidências de staging

Verifica um manifesto contra ficheiros de evidência reais, exigindo uma raiz explícita e rejeitando ficheiros em falta, vazios, symlinks, path traversal e hashes divergentes. Consulte `STAGING_EVIDENCE_INTEGRITY_V43.md`. A aprovação continua a ser apenas para revisão manual.


### v46 staging evidence checks

The staging security acceptance verifier rejects stale or timezone-naive concurrency reports, malformed fixture UUIDs, duplicate worker identities, worker errors, and incomplete reconciliation cleanup. See `STAGING_EVIDENCE_FRESHNESS_V46.md`.


## v52 — concurrent hosted lead writes

The v52 patch adds transaction-scoped PostgreSQL advisory locks to serialize same-key idempotency and same-lead writes, including first writes where no snapshot row exists yet. The PostgREST adapter now normalizes SQLSTATE unique/serialization conflicts into HTTP 409 at the API boundary. Apply migration `0024_operational_lead_concurrency.sql` after `0023` and validate on a dedicated Supabase staging project before production use. Local tests do not substitute for remote concurrency evidence.

## v55 — Read-only live staging probe

Added `scripts/staging_readonly_probe_v55.py`, an environment-configured, HTTPS-only, read-only probe that checks API health, each test user's access to its own existing lead, and reciprocal cross-tenant denial. It never creates or updates leads and never prints bearer tokens. Configure the seven `STAGING_*` variables described in `STAGING_PROBE_V55.md`. Live probe was not run without staging credentials.
\n\n## v56 — Automated CI and staging acceptance\n\nAdded `.github/workflows/staging-acceptance-v56.yml`: static quality checks run on pushes and pull requests; a manually dispatched job runs the read-only v55 staging tenant-isolation probe only after static checks pass, then uploads a sanitized JSON report. See `CI_STAGING_ACCEPTANCE_V56.md`. Live staging remains unverified until GitHub Environment secrets are configured and the workflow is run against the actual staging API.\n\n\n## v57 — Production promotion safety gate\n\nAdded `scripts/verify_production_promotion_v57.py`, which requires signed, fresh staging evidence, valid semantic acceptance checks, and explicit disabled settings for live outbound messaging and payments. This is a fail-closed decision gate only; it does not deploy or authorize production automatically. See `PRODUCTION_PROMOTION_GATE_V57.md`.\n\n\n### v58 release artifact binding\n\nUse `scripts/verify_production_promotion_v58.py` to require signed staging evidence to match the exact commit and artifact intended for manual promotion. See `RELEASE_ARTIFACT_BINDING_V58.md`.\n\n\n### v59 release provenance\nSee `RELEASE_PROVENANCE_V59.md` for the CI-generated source archive and commit-bound SHA-256 manifest.\n\n\n## v60: Commercial demo funnel\n\nSee `COMMERCIAL_REVENUE_CYCLE_V60.md`. Run the API and open `/offer` to test the real-estate agency demo-request funnel locally. Configure `PUBLIC_INTAKE_ADMIN_TOKEN` to enable the protected internal queue.\n