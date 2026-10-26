# Project state — v54

## v54 — Signed staging release decision
- Added `scripts/verify_staging_release_v54.py`: verifies HMAC integrity and then applies v53 acceptance semantics.
- Added regression tests proving signatures do not bypass freshness, isolation, or live-action policy checks.
- Added static release-gate coverage and runbook `STAGING_RELEASE_DECISION_V54.md`.
- Local-only validation; no live Supabase staging or provider sandbox certification.

# Project state — v51

## v51 — Hosted operational lead storage
- Added caller-JWT Supabase/PostgREST lead repository and atomic RPC contract.
- Added migration 0023 for tenant-scoped snapshots, idempotency and append-only events.
- Production lead endpoints no longer use SQLite; hosted mode requires authenticated principal.
- Added RPC signature to static checker.
- Local validation only; live Supabase migration, RLS, grants and concurrency remain unverified.

# Project state — v31

## v31 — Pilot monitoring and daily exceptions
- Added tenant-scoped daily KPI/alert report over local JSONL exports.
- Normalizes timezone-aware timestamps to UTC and fails closed for missing/naive timestamps.
- Drops arbitrary payloads and PII; emits aggregate metrics only.
- Added alert thresholds for unknown provider outcomes, failed actions and human-intervention rate.
- Added static release-gate check and CLI regression tests.
- Local-only validation; no live Supabase/provider integration or delivered alert destination is certified.

# Project state — v30

## v29 — End-to-end acceptance protocol
- Added `E2E_ACCEPTANCE_PROTOCOL_V29.md` with the local golden path, negative cases, staging commands, acceptance criteria, and a fail-closed release decision.
- Added acceptance tests for the end-to-end lead-to-active path, webhook tenant mismatch, duplicate payment events, and mandatory approval for custom contracts.
- Local tests remain simulations; no remote Supabase or provider sandbox is certified by this release.

# Project State — AI Sales System v28

## Release classification
Pilot/staging candidate only. Not production-authorized; no live Supabase, WhatsApp, Calendar,
Stripe, or email account has been verified in this build session.

## v17 implementation
- Topic-based durable event dispatcher: `app/orchestrator/runtime.py`.
- Supabase outbox worker glue: `app/workers/durable_service.py`.
- Explicit permanent outbox failure support: `sql/migrations/0015_permanent_outbox_failures.sql`.
- Worker passes tenant and lease identity from the claimed DB row, not from event payload.
- Transient failures are rescheduled with bounded exponential backoff.
- Deterministic failures are marked permanent and sent to dead-letter state.
- Error messages intentionally avoid logging provider response bodies and user payloads.

## Guarantees and limits
- Local tests use mocks and do not prove remote Supabase migrations, RLS, provider behavior,
  OAuth setup, webhook delivery, or deployment.
- Outbox delivery is at-least-once. External handlers must honor the stable idempotency key.
- No production credentials are included. Outbound remains disabled by default.

## Next gates
1. Apply migrations 0001–0015 in disposable Supabase staging.
2. Validate RLS and RPC grants with owner/admin/member/viewer test accounts and two tenants.
3. Run worker against staging outbox with a no-op handler, then inject transient/permanent failures.
4. Validate provider sandbox requests and idempotency before enabling any outbound action.
5. Configure secrets in deployment environment and run release checklist.

## v18 staging-readiness update

Added `scripts/staging_smoke.py`, a read-only Supabase connectivity check intended only for a dedicated staging project. It verifies config shape, Auth health and table endpoint access without writes. Automated tests use mocked HTTP responses. No real Supabase project was accessed in this build session; staging/RLS/provider validation remains pending.

## v19 — RLS/privilege hardening

- Added migration `0016_rls_privilege_hardening.sql`.
- Removed authenticated tenant-wide mutation policies for `actions` and `events`; made them select-only.
- Removed direct client access policy for `outbox_events`.
- Replaced approval resolution with an atomic `SECURITY DEFINER` RPC that validates `auth.uid()`, tenant membership, OWNER/ADMIN/MANAGER role, pending state, and a bounded reason; direct audit insertion policy removed.
- Restricted outbox claim and runtime mutation RPCs to `service_role`, with claim parameter bounds.
- Added read-only two-user staging RLS probe and mocked/static tests.
- Status: local tests only; live Supabase RLS/RPC grant verification remains required.

## MVP v20 — Release gate
- Added fail-closed static and staging configuration checks.
- Validates migration manifest/order, key v19 SQL privilege guardrails, safe example defaults,
  absence of local environment files, HTTPS Supabase origin, distinct public/server keys,
  strong dashboard token, and disabled live actions during staging.
- Added `scripts/release_gate.py`; it is deliberately offline and read-only.
- Local validation: 119 tests passed; Python compilation passed; static release gate passed.
- Not yet verified: real Supabase migration application, hosted RLS/RPC grants, worker behavior
  against the remote queue, or provider sandbox execution. Release remains pilot-only.

## MVP v21 — Action Gateway retry and payment safety

- Fixed a retry dead-end in `InternalActionGateway`: retryable provider outcomes are not cached in process memory, allowing a subsequent invocation to retry. Successful and definitive non-retryable results remain cached for local idempotency. External provider idempotency keys remain mandatory because a timeout can be ambiguous.
- Added an explicit per-organization `payments_enabled` feature flag, defaulting to false. Creating a checkout now requires that flag in addition to the global automation switch, tenant match, and any required human approval.
- Added regression tests for transient recovery, duplicate suppression after success, default payment-off behavior, approval requirements, and tenant isolation.
- Validation is local and uses mock providers. The in-memory cache is not a substitute for a durable idempotency table in multi-worker production; payment flags must be populated from trusted persisted organization settings, never caller-supplied request data.
- Production/staging provider verification remains pending; live outbound and payments must remain disabled until real sandbox tests pass.


## MVP v22 — durable cross-worker action idempotency

- Added `SupabaseIdempotencyStore`, wired into `InternalActionGateway` through an optional durable store adapter. The in-memory fallback remains for local tests/development only.
- Added migration `0017_durable_action_idempotency.sql`: tenant/action/key uniqueness, row-locking claim RPC, bounded worker leases, result persistence, and service-role-only grants. Provider I/O remains outside database transactions.
- Success and definitive failure outcomes replay from durable storage; retryable outcomes can be claimed again; concurrent attempts receive `IN_PROGRESS` instead of executing twice.
- Provider-side idempotency remains mandatory to cover ambiguous timeouts after the provider accepted a request but before the result was durably recorded.
- Added static release-gate checks and tests using a fake RPC repository. These tests do not prove actual Postgres locking, SQL compilation, RLS/grants, or hosted behavior.
- Status remains pilot/staging candidate. Migration 0017 must be applied and concurrency-tested against a real disposable Supabase/Postgres staging environment before live use.


## v23 — webhook inbox and recovery safety
- Added migration `0018_provider_webhook_inbox.sql` with tenant-scoped unique provider event IDs, row-locked claim/finish RPCs, leases, retryable failures, and service-role-only execution.
- Added `SupabaseWebhookInbox` repository adapter; provider signature verification must happen before `claim`.
- Added timestamp ordering helper for state snapshots only. It must not be used to discard distinct payment/ledger events.
- Added release-gate checks and tests for duplicate/replayed events, concurrent claims in the test double, lease recovery semantics, and out-of-order state snapshots.
- Validation is local/static with fake repositories; no live Supabase/Postgres staging validation has been performed.

## MVP v24 — Runtime integration contract
- Added `tests/test_v24_runtime_integration.py` covering the durable worker + dispatcher application path and failure injection.
- Tested success, tenant mismatch rejection, missing handler dead-letter, transient retry/backoff, handler-requested retry, lease loss, concurrent claims in a synchronized fake repository, malformed payloads, duplicate registrations, and tenant-scoped idempotency keys.
- The concurrency test double only validates application-layer assumptions; it is not a substitute for multi-connection Postgres tests.
- Release remains staging-only until migrations 0001–0018 are applied to a disposable Supabase/Postgres project and actual RLS, RPC grants, concurrent claims, webhook leases, and provider sandbox behavior are evidenced.


## v25 — RPC contract drift checks
- Added `scripts/check_rpc_contracts.py` to compare latest SQL function signatures with Python RPC contracts and verify service-role-only grants for worker RPCs.
- Added read-only `sql/staging_contract_check.sql` for deployed function existence, RLS flags, and grants.
- Integrated static RPC contract verification into the release gate.
- Local validation only; the staging SQL must still be run against an actual staging database.

## MVP v26 — ambiguous provider outcome policy
- Added a provider-neutral reconciliation decision policy that distinguishes confirmed outcomes, definitive failures, and unknown outcomes.
- Timeouts and incomplete provider responses are treated as UNKNOWN; they are never assumed to mean the provider did nothing.
- Recovery prefers an authoritative provider lookup; otherwise a retry is permitted only where the provider supports idempotency and the exact original key is reused. If neither is available, route to manual review.
- Added regression tests for explicit failures, incomplete results, timeout branches, and rejection of fresh idempotency keys.
- This is a policy layer, not a live provider reconciler: provider-specific lookup endpoints and sandbox credentials remain required to establish real external state.


## MVP v27 — staging security matrix
- Added read-only SQL evidence query for RLS enabled/forced state, effective table privileges, and grants on critical runtime/approval RPCs.
- Added tests ensuring the query covers critical tables and functions and does not contain mutating SQL statements.
- Integrated matrix presence/safety checks into the static release gate.
- This does not certify live security: real staging tenant isolation and OWNER/ADMIN/MANAGER/MEMBER/VIEWER behavior still require tests with actual accounts and fixtures.


## MVP v28 — Pilot readiness report
- Added `PILOT_READINESS_REPORT.md` documenting local evidence, remote evidence still required, mandatory staging blockers, safe pilot defaults, acceptance criteria, and explicit NO-GO for live commercial automation.
- Added `scripts/check_pilot_readiness.py` and wired it into the static release gate so missing safety sections block release.
- Added tests ensuring the report retains two-tenant, cross-tenant denial, provider timeout-after-acceptance, and disabled live-action requirements.
- Validation performed locally: 187 tests passed; Python compilation passed; 14/14 RPC contract checks passed; pilot readiness report check passed; static release gate passed.
- No live Supabase, provider sandbox, real account role matrix, or hosted concurrency tests were run. Live pilot remains blocked pending the evidence listed in the report.

# MVP v30 — Controlled pilot operations pack
- Added tenant-scoped CSV lead validation that rejects cross-organization rows, validates email/consent fields, reports duplicates, and marks opt-out/unknown-consent records as non-contactable.
- Added pilot KPI calculations for funnel counts, response/qualification/booking rates, human intervention, failed actions, unknown provider outcomes, and duplicate suppression.
- Added a read-only CLI validator and sample CSV template. Validation performs no database writes and sends no messages.
- Added `PILOT_OPERATIONS_V30.md` with staged intake steps, launch guardrails, KPI review, and exit criteria. The static release gate now checks that the operations pack and safeguards are present.
- Local tests only; no live Supabase/provider integration is certified. Live pilot remains blocked until staging evidence is recorded.

## MVP v32 — Exception center & resolution workflow
- Added a tenant-scoped exception queue for unknown provider outcomes, failed actions, invalid webhook signatures, human approvals, payment reconciliation and dead-letter work.
- Queue entries use deterministic IDs and generic descriptions; raw provider errors and contact PII are omitted. Repeated source events deduplicate in the exported queue.
- Added role-gated assignment, acknowledgement, resolution and dismissal transitions, including cross-tenant denial and bounded resolution notes.
- Added a read-only JSONL CLI, exception-center documentation and a static release-gate check.
- This version does not include durable queue persistence, authenticated API endpoints, notifications or live staging validation. Production must add database uniqueness, atomic audit persistence, concurrency control and database-enforced membership checks.

## v33 — Durable Exception Center

Exception management now has a durable SQL design: unique tenant/source identity, transactional state transitions and audit rows, row locking, and membership/assignee checks inside PostgreSQL. Python repository uses service-role RPCs only from trusted backend code. Local tests use a fake repository; no remote database was contacted. Live staging verification remains a launch blocker.

## MVP v34 — worker exception-center integration
- Wired an optional trusted-backend exception store into the durable worker. Permanent failures are recorded in the outbox first and then emitted to the tenant-scoped exception center using the existing idempotent v33 RPC.
- Added retry-budget exhaustion behavior: transient failures continue with backoff until `max_attempts`, then become dead-lettered and eligible for a durable exception record.
- Exception summaries are fixed generic text; event payloads, contact PII and raw exception/provider messages are not forwarded. If exception persistence fails, the worker reports an exception-recording error without claiming the work succeeded.
- Lease-loss paths do not create exceptions because the worker no longer owns the final outcome. The exception store remains optional for backwards compatibility.
- Added regression tests and a release-gate check for this integration.
- Local fake-repository tests only. PostgreSQL atomicity, real worker leases, remote Supabase RPC grants and provider sandbox flows remain unverified; live outbound and payments must remain disabled.

## MVP v35 — controlled exception replay policy

- Added fail-closed replay decision policy with sensitive-code reconciliation precedence, allowlisted transient failures, confirmed-not-applied external outcomes, stable idempotency key requirement, exception-state checks, and a configurable bounded replay budget (1–10; default 3).
- Added a read-only JSON CLI that emits plans only; it never writes to storage, enqueues work, or calls providers. Every result explicitly has `execute: false`.
- Added regression tests for reconciliation-required codes, unknown provider outcomes, idempotency, budget exhaustion, invalid state, and CLI behavior.
- Live provider/database replay is intentionally not implemented; staging validation remains required.

## MVP v36 — audited replay approvals
- Added migration `0020_audited_replay_approvals.sql` with a tenant-scoped replay request ledger, unique replay slots, row-locking RPCs and append-only request/decision audit entries.
- Requests require an allowlisted transient failure, confirmed `NOT_APPLIED` provider outcome, eligible exception state, bounded replay number and the original idempotency key.
- Manager approval/rejection is audited, and a requester cannot approve their own replay request.
- Added trusted-backend repository methods and regression tests. Approval records a decision only; no provider dispatch or queue replay is implemented in v36.
- Local tests and static checks do not prove deployed PostgreSQL behavior. Staging migration, tenant-isolation, concurrency and role tests remain required; live outbound and payments remain disabled.

## Latest increment: v37 controlled replay dispatch

Approved exception replay requests can now be atomically reserved by a trusted worker, passed to an injected executor with the original idempotency key, and finished through a worker-owned lease. Unknown outcomes and finish-persistence failures require reconciliation. Expired dispatch leases are not automatically replayed. The implementation is covered by local fake-store tests only; apply migration 0021 and complete the documented staging acceptance checks before connecting live providers.

## v38 staging acceptance status

A read-only SQL catalog probe, fail-closed CSV evaluator, and operational staging rehearsal checklist are included. This provides a reproducible acceptance process but does not mean staging has been run. Live Supabase validation remains pending until an operator runs the SQL probe and the two-tenant/provider-sandbox rehearsal in `STAGING_REPLAY_ACCEPTANCE_V38.md`. Live outbound and payments remain disabled.

## v39 staging rehearsal evidence
- Added a fail-closed manifest verifier and example template to collect operational staging artifacts consistently.
- Seven required checks cover tenant isolation, concurrent claims, provider idempotency, ambiguous outcomes, expired leases, audit completeness, and safe live-action defaults.
- A successful manifest yields only `GO_FOR_MANUAL_REVIEW`; a human must inspect referenced artifacts and independently verify their digests. This is not evidence that staging was actually run and not launch authorization.
- Live Supabase and provider sandbox tests remain pending; live outbound and payments stay disabled.

## v40 staging rehearsal runner

The staging rehearsal now has an opt-in runner (`scripts/run_staging_rehearsal.py`) that captures evidence from existing read-only Supabase smoke and tenant-isolation probes, hashes artifacts, and emits a manifest. It refuses production and does not apply migrations or call business providers. Missing live probes are marked FAIL. Local tests validate orchestration and fail-closed behavior; remote staging has not been run in this build.

## MVP v41 status — replay concurrency and crash windows

- Added deterministic thread-race tests for two workers attempting the same replay request.
- Added ambiguous-provider-outcome and finish-persistence-failure tests.
- Fixed the dispatcher to fail closed and return a redacted `RECONCILIATION_REQUIRED` result if finish persistence raises an unexpected exception.
- Targeted v37/v41 tests: 10 passed. RPC contract checks: 28/28 passed. Python compilation and static release gate passed.
- Full pytest suite timed out after approximately 78% of tests had reported passing; full-suite completion is unverified.
- These are in-memory contract tests only. Live Supabase/Postgres concurrency, deployed RLS and provider sandbox behavior remain unverified.

## MVP v42 status — expired replay lease recovery

- Added a repository method for the existing `reconcile_expired_exception_replays` RPC, validating the grace period and redacting remote errors.
- Added a staging-only explicit maintenance CLI. Without `--execute`, it is a no-op; it refuses any `APP_ENV` other than exactly `staging`.
- Stale `DISPATCHING` leases are moved to `RECONCILIATION_REQUIRED`, not back to `APPROVED`; external outcome still needs reconciliation.
- Added tests for request contract, PostgREST result shapes, cutoff validation, error redaction, SQL grants/audit invariants, and CLI opt-in controls.
- Local tests do not establish live PostgreSQL, RLS, or provider behavior. No live staging connection was performed in this build.

## Estado v43 — Integridade das evidências

A CLI de verificação de staging exige agora `--evidence-root` e valida os ficheiros reais referenciados no manifesto, incluindo existência, conteúdo não vazio, caminhos seguros, ausência de symlinks e correspondência SHA-256. Esta verificação não prova que os testes remotos foram realmente executados; Supabase/PostgreSQL staging e provider sandbox continuam pendentes.

# Project state — AI Sales System v44

- Added an explicitly opt-in staging probe for a real two-worker race on `claim_exception_replay`.
- The probe is destructive to its disposable fixture by design: a winner is finished as `OUTCOME_UNKNOWN` and must be reviewed in reconciliation.
- It does not call providers and refuses to run unless `APP_ENV=staging`, `--execute`, `--confirm-disposable-fixture`, HTTPS Supabase URL, service-role credential and fixture UUIDs are present.
- Local tests cover result interpretation and opt-in guardrails. No live staging run is claimed in this package; the external run remains pending operator credentials and disposable fixture setup.

# Project state — AI Sales System v45

- Added a fail-closed staging security acceptance command that combines the read-only two-user RLS/tenant-isolation probe with a separately generated v44 concurrency report.
- Requires explicit `APP_ENV=staging`; missing concurrency evidence produces `NO_GO`. Concurrency evidence must show exactly two workers, exactly one winner, no provider call, and cleanup evidence for the winner.
- The combined report includes the concurrency artifact SHA-256, not its full worker details. The command does not write to Supabase or call a provider.
- Local validation covers report schema and fail-closed logic. Actual staging RLS and concurrent RPC behavior remain unverified until operator runs it with two distinct staging users and a disposable replay fixture.

### v47 — Signed staging evidence
Staging report JSON can now be wrapped in an HMAC-SHA256 envelope and verified later. This detects content changes after signing, assuming the key remains secret. It does not authenticate a unique human identity, prove that remote tests actually ran, or replace manual review. No live Supabase/provider validation was performed by this change.

# Project state — AI Sales System v48

- Added an offline, deterministic real-estate lead journey simulator in `app/simulation/real_estate.py` and CLI `scripts/simulate_real_estate_golden_path.py`.
- The flow simulates research, permission-gated contact actions, lead scoring, shortlist preparation, follow-up, and visit-slot proposal/request.
- Missing consent and do-not-contact suppress contact actions. Tenant mismatch and automation kill switch fail closed.
- Discount requests above 10%, custom contracts, legal questions, serious complaints, and strategic-client flags require human review.
- Actions are simulation-only, with `external_side_effect: false`; example fixture/report make no live provider calls.
- Added tests and static release-gate coverage. The rule-based score is a prototype and has not been calibrated against real conversion outcomes.
- No live Supabase/Postgres, deployed RLS/RPC grants, CRM, messaging, calendar or payment sandbox validation is claimed. Live outbound and payments remain disabled.

## Current release: MVP v49

The v49 increment adds local durable persistence for the real-estate lead journey. It includes tenant-scoped lead snapshots, optimistic version checks, transactionally committed idempotency records and audit events, a local rehearsal CLI, and the prepared Supabase migration `0022_real_estate_lead_persistence.sql`. The local SQLite adapter and tests do not certify hosted PostgreSQL RLS or a live integration. Apply migration 0022 only to dedicated staging after review; live outbound and payments remain disabled pending staging evidence and explicit launch approval.


# Project state — v50

## v50 — Operational lead API
- Added tenant-scoped API endpoints for lead upsert, listing, retrieval, and audit timeline.
- API uses existing dashboard authentication. Write requests require an idempotency key; optimistic version checks reject stale updates.
- Local/pilot mode uses the SQLite lead persistence adapter. Production mode fails closed rather than using a local SQLite database; a hosted lead repository adapter remains a deployment blocker.
- Tests cover authentication, read/write, audit trail, duplicate request handling, tenant isolation, version conflicts, and production fallback rejection.
- Local validation: 341 tests passed. No remote Supabase/Postgres or provider sandbox was accessed.


## v52 status
- Hosted lead-write concurrency guard implemented in migration 0024 with stable advisory-lock order (idempotency key then lead).
- Supabase/PostgREST SQLSTATE conflict mapping normalized to the API's 409 contract.
- Local regression tests cover conflict mapping and migration guardrails.
- Not yet applied to a live Supabase project; no claim of remote concurrency validation.

## v53 status
- Added `scripts/verify_staging_acceptance_v53.py` and `STAGING_ACCEPTANCE_V53.md` for fail-closed verification of operator-collected staging acceptance evidence.
- Evidence must be fresh (24h), cover two distinct organizations, report all required auth/isolation/idempotency/concurrency/version/migration checks as true, keep live actions disabled, and contain no credential-like fields.
- Local verifier tests and static gate only. No remote Supabase project was accessed; do not represent staging as accepted until evidence is collected and verified.

## v55 — Read-only live staging probe

Added `scripts/staging_readonly_probe_v55.py`, an environment-configured, HTTPS-only, read-only probe that checks API health, each test user's access to its own existing lead, and reciprocal cross-tenant denial. It never creates or updates leads and never prints bearer tokens. Configure the seven `STAGING_*` variables described in `STAGING_PROBE_V55.md`. Live probe was not run without staging credentials.
\n\n## v56 — Automated CI and staging acceptance\n\nAdded `.github/workflows/staging-acceptance-v56.yml`: static quality checks run on pushes and pull requests; a manually dispatched job runs the read-only v55 staging tenant-isolation probe only after static checks pass, then uploads a sanitized JSON report. See `CI_STAGING_ACCEPTANCE_V56.md`. Live staging remains unverified until GitHub Environment secrets are configured and the workflow is run against the actual staging API.\n\n\n## v57 — Production promotion safety gate\n\nAdded `scripts/verify_production_promotion_v57.py`, which requires signed, fresh staging evidence, valid semantic acceptance checks, and explicit disabled settings for live outbound messaging and payments. This is a fail-closed decision gate only; it does not deploy or authorize production automatically. See `PRODUCTION_PROMOTION_GATE_V57.md`.\n\n\n## v58 release artifact binding\n\nThe v58 gate binds signed staging evidence to an exact Git commit and SHA-256 artifact digest; it is fail-closed and never deploys. Local tests validate matching/mismatching evidence. No remote Supabase or CI run is implied.\n\n\n## v60 — Commercial revenue cycle foundation\n\nThe project now has an actual first commercial entry point: a Portuguese offer page, a durable demo-request form, and a protected local intake queue. This is a first step toward customer acquisition, not a fully autonomous company. Pricing remains a hypothesis. Payments, automated follow-up, calendar booking, production hosting, legal identity/privacy policy, and remote integration validation remain outstanding.\n