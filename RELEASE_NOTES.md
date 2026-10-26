# Release notes — v54

- Added a signed staging release decision that verifies the HMAC envelope and then re-runs all v53 semantic acceptance rules.
- A valid signature cannot override stale evidence, failed tenant isolation/concurrency checks, missing checks, credential-like fields, or enabled live actions.
- Added regression tests for tampering, unsigned evidence, stale evidence, wrong keys and policy failures.
- Added the v54 decision verifier to the static release gate.
- Local validation only; no remote Supabase or provider sandbox was accessed. Live outbound and payments remain disabled.

# Release notes — v51

- Production lead API now routes to Supabase using the caller JWT and RLS.
- Added migration 0023 for atomic lead snapshot/event/idempotency writes.
- SQLite remains local/pilot only; no production fallback.
- Remote staging validation remains required.


## v29 — End-to-end acceptance protocol
- Documented golden-path and negative-path acceptance criteria from lead intake to active customer.
- Added 5 acceptance protocol tests covering tenant-safe webhooks, duplicate events, payment-gated activation, and human approval boundaries.
- Remote staging and provider sandbox results remain pending; live outbound and payments must stay disabled until evidence is recorded.

# Release notes — AI Sales System MVP v25

## Changes
- Retryable provider failures are no longer cached by the in-process action gateway, allowing retries to reach the provider again.
- Checkout/payment actions require an explicit trusted organization flag (`payments_enabled=True`), false by default.
- Regression tests cover transient recovery, idempotency after success, payment default-off, approval checks, and tenant mismatch.

## Validation performed locally
- `python -m pytest -q`: 126 passed.
- `python -m compileall -q app scripts`: passed.
- `python scripts/release_gate.py --static-only`: passed.

## Known limitations
- No live Supabase instance, OAuth integration, or provider sandbox was accessed in this build.
- Gateway result cache is process-local, not durable or shared between workers. Production must use durable idempotency storage and provider idempotency keys.
- The payment flag must come from trusted server-side organization settings. Do not derive it from browser input or event payloads.
- Outbound and live payments remain disabled until staging evidence and sandbox verification are complete.


## v22 — durable action idempotency

Added tenant-scoped persistent action idempotency and worker lease arbitration via Supabase RPCs. The gateway can use the shared durable store across API/worker instances. Local validation uses a fake RPC repository; hosted Postgres concurrency and provider sandbox tests remain release blockers.


## v23 — durable webhook inbox
- Adds a database-backed webhook inbox with unique provider event IDs, row-lock arbitration, lease ownership, retryable completion, and server-only RPC grants.
- Adds a repository adapter and a timestamp guard for state snapshots; distinct financial events must still be processed individually.
- Adds static release-gate checks for migration ordering and privilege hardening.
- Local tests use simulated repositories; live PostgreSQL concurrency and provider sandbox tests remain release blockers.

## MVP v24 — Runtime integration contract
- Added application-layer integration tests for the durable worker + topic dispatcher path.
- Covers successful dispatch, tenant identity mismatch, unknown handlers, retryable handler outcomes, transient exceptions, safe error messages, lease loss, concurrent claims in a thread-safe repository test double, payload shape validation, duplicate handler registration, and tenant-scoped idempotency keys.
- These tests validate wiring and error handling with a fake repository. They do not establish PostgreSQL row-lock behavior, real worker process concurrency, or provider-side exactly-once execution.
- Runtime still provides at-least-once delivery. Provider requests must carry stable idempotency keys; ambiguous timeouts require reconciliation or provider lookup before any blind retry if the provider lacks idempotency support.


## v25 — RPC Contract Verification
- Static checker detects drift between Python RPC request arguments and the latest SQL migration definitions.
- Checks worker RPC execute grants and client-role revocations.
- Adds a read-only SQL query for inspecting deployed staging catalog state.
- Release gate now blocks if RPC contract checks fail.
- No live Supabase connection was made by these local checks.


## v25 — RPC Contract Verification

- Added `scripts/check_rpc_contracts.py` to compare the latest SQL function signatures against the Python RPC argument contracts.
- Added privilege checks for service-role grants and client-role revocations on worker RPCs.
- Integrated RPC contract checks into the static release gate.
- Added `sql/staging_contract_check.sql`, a read-only query for deployed function existence, key-table RLS flags, and execution grants.
- Updated migration and release documentation.

### Validation performed locally
- `pytest -q`: 164 passed.
- `python -m compileall -q app scripts tests`: passed.
- `python scripts/check_rpc_contracts.py`: 14/14 passed.
- `python scripts/release_gate.py --static-only`: passed.

### Known limitations
- No live Supabase instance or external provider sandbox was accessed. The SQL staging check must be run against a real dedicated staging project.
- Static catalog checks do not certify RLS policy behavior or transaction/concurrency semantics.

## MVP v26 — ambiguous outcome reconciliation policy
- Added `app/integrations/reconciliation.py` to prevent timeouts being misclassified as definitive failures.
- Recovery decision order: provider lookup, same-key retry only when provider idempotency is supported, otherwise manual review.
- Added regression tests for incomplete results and idempotency-key preservation.
- No external API or live sandbox was called as part of this release.


## v27 — Staging security evidence
- Added `sql/staging_security_matrix.sql` to report critical-table RLS status, effective table privileges, and sensitive RPC grants.
- Added static regression tests and a release-gate check for the read-only matrix.
- No remote Supabase calls are made by local tests; this is evidence preparation, not live security certification.


## MVP v28 — Pilot readiness report
- Consolidates local evidence and remote blockers in `PILOT_READINESS_REPORT.md`.
- Lists mandatory staging checks for two-tenant isolation, role-based permissions, RPC grants, concurrency, provider sandbox failures, secrets, backup/restore, monitoring, and rollback.
- Adds `scripts/check_pilot_readiness.py`; static release gate now fails if critical safety/readiness statements are missing.
- Safe defaults explicitly require `OUTBOUND_ENABLED=false` and `ENABLE_LIVE_PAYMENTS=false` until staging evidence and owner sign-off.

### Validation performed locally
- `python -m pytest -q`: 187 passed.
- `python -m compileall -q app scripts`: passed.
- `python scripts/check_rpc_contracts.py`: 14/14 passed.
- `python scripts/check_pilot_readiness.py`: passed.
- `python scripts/release_gate.py --static-only`: passed.
- No remote Supabase or provider sandbox was accessed; release remains NO-GO for live commercial automation.

## MVP v30 — Controlled pilot operations
- Safe, tenant-scoped CSV lead validation; opt-in timestamp required for contactable leads; opt-out and unknown-consent rows are never marked contactable.
- Duplicate detection within an import, input rejection reporting, and cross-tenant row rejection.
- Provider-neutral pilot KPI calculator and operational runbook.
- Validation is read-only and does not send messages or write to a database.


## MVP v31 — Pilot monitoring
- Added `scripts/daily_pilot_report.py` and `app/pilot/monitoring.py` for read-only, tenant-scoped daily reports.
- Added UTC date filtering, malformed-input fail-closed behavior, PII minimization, and actionable operational alerts.
- Added `PILOT_MONITORING_V31.md` and release-gate coverage.
- Live event export, alert delivery, remote tenant isolation and provider behavior remain unverified.

## v32 — Exception Center
- Introduced privacy-minimized exception triage and role-gated lifecycle transitions.
- Added read-only CLI and regression tests for tenant isolation, deterministic deduplication, invalid inputs, role restrictions and terminal-state rules.
- Release gate now checks the exception-center pack and documented limitations.
- Local-only validation; durable persistence and live staging evidence remain blockers.

## v33 — Durable Exception Center

- Added migration `0019_durable_exception_center.sql` for tenant-scoped durable exceptions and transition audit history.
- Added idempotent exception creation keyed by organization/source type/source ID.
- Added atomic, row-locked transitions with SQL-side organization membership and assignee checks.
- Added `SupabaseOperationalExceptionStore` and RPC signature/privilege checks.
- Local mocked contract tests cover input validation, tenant forwarding, safe errors, and migration guardrails.
- Live Supabase staging validation is still required; do not infer production readiness from local tests.

## MVP v34 — Worker exception-center integration

- Durable worker can persist permanent/dead-letter failures into the v33 operational exception center.
- Retryable failures back off until the configured attempt budget is exhausted; exhausted items become dead-lettered.
- Exception creation is tenant-scoped and database-idempotent through the existing RPC; generic summaries exclude payloads, PII and raw provider errors.
- Exception persistence failures are counted separately and cannot turn a failed outbox item into a reported success.
- Added five tests for permanent failures, retry behavior, exhaustion, exception-store outage and backwards compatibility.
- Local tests and static release gate only; live Supabase/Postgres staging remains required.

## MVP v35 — Controlled exception replay policy

Adds a read-only, fail-closed planner for exception replay. Only an allowlisted transient failure with a confirmed not-applied outcome, a stable original idempotency key, an eligible exception state, and remaining bounded replay budget can produce `REPLAY_PLAN`. Unknown outcomes and payment/webhook-sensitive exceptions are sent to reconciliation; the planner never executes a replay. Includes a JSON CLI and policy tests. No live Supabase/provider integration was exercised.

## MVP v36 — audited replay approvals

- Added durable tenant-scoped replay request and audit tables, with a unique replay slot per exception and bounded replay numbering.
- Added service-role-only RPCs for safe replay requests and independent manager decisions. Requests require allowlisted transient failures, confirmed not-applied outcomes and the original idempotency key.
- Added repository methods with fail-closed input validation and regression tests.
- Approval is only a durable decision, not an execution trigger. No queue mutation or provider call occurs in v36.
- Local validation only; staging SQL/RLS/role/concurrency checks remain outstanding.

## v37 — Controlled replay dispatch

- Added atomic tenant-scoped claim and lease ownership for approved replay requests.
- Added guarded finish states and audit events for success, definite failure, and ambiguous outcome.
- Added stale-lease reconciliation; expired dispatches are not automatically replayed.
- Added backend dispatcher with injected executor, original idempotency key preservation, redacted generic failure codes, and fail-closed behavior.
- Added local fake-store tests and static release-gate checks.
- No live provider or Supabase staging validation was performed.
- Updated read-only staging contract/security SQL to include the new replay tables and RPCs.

## v38 — Staging replay acceptance pack

- Added a read-only SQL catalog probe for replay RPC signatures, service-role execution, client-role revocations, RLS flags, required dispatch columns, atomic locking, and stale-lease reconciliation.
- Added a fail-closed CSV evaluator that rejects failed, missing, duplicate, or partial catalog evidence.
- Added a staging rehearsal runbook for cross-tenant isolation, concurrent claim, provider ambiguity, lease expiry, and audit evidence.
- No provider calls, writes, migration application, or live-action enablement are performed by these tools.
- Local tests do not constitute a live Supabase staging validation.

## MVP v39 — staging rehearsal evidence verifier
- Added a fail-closed JSON manifest verifier for seven operational staging checks: tenant isolation, concurrent claim, provider idempotency, unknown-outcome reconciliation, expired-lease behavior, audit completeness, and disabled live actions.
- Requires UTC timestamps, relative evidence references, SHA-256 digests, unique check names, and PASS results. Missing or blocked checks result in NO-GO.
- Emits a machine-readable report with `GO_FOR_MANUAL_REVIEW`, never a launch approval. It does not connect to staging, verify artifact contents, calculate artifact digests, or claim that a rehearsal ran.
- Added tests and release-gate coverage. Live Supabase/provider validation remains an operator task; outbound and live payments remain disabled.

## MVP v40 — staging rehearsal runner

- Added an opt-in staging runner that invokes only existing read-only Supabase smoke and two-tenant RLS probes.
- Captures stdout/stderr and exit status into artifacts, calculates SHA-256 digests, and emits a required-check manifest plus summary.
- Refuses production mode and requires `--execute` for any network access.
- Concurrency, provider idempotency, ambiguous-outcome recovery, expired-lease, and audit checks remain explicit FAIL until actual staging probes are implemented; no false readiness claim.
- Added automated tests for fail-closed behavior, production refusal, and artifact digest integrity.
- No live Supabase or provider validation is claimed by this package build.

## MVP v41 — replay concurrency and crash-window hardening

- Added deterministic two-worker race tests around the replay dispatcher contract; verifies a single executor call and preservation of the original idempotency key.
- Added a provider-side-effect-then-timeout test; ambiguous outcomes are marked for reconciliation and are not retried in-process.
- Hardened finish-persistence error handling: any unexpected store exception returns a redacted reconciliation-required result instead of escaping or claiming success.
- Added release-gate coverage and an explicit evidence boundary: in-memory tests do not prove PostgreSQL locking, deployed RLS, or provider sandbox idempotency.
- Full project pytest run exceeded the available execution limit after approximately 78% of tests had reported passing; targeted v37/v41 tests and static checks completed successfully.
- No live Supabase or provider sandbox was used; production outbound and payments remain disabled.

## MVP v42 — expired replay lease recovery

- Exposed the existing stale-dispatch reconciliation RPC through the trusted backend repository with bounded cutoff validation and redacted failures.
- Added `scripts/reconcile_expired_replays.py`: dry-run by default; mutation requires `--execute` and `APP_ENV=staging` explicitly.
- Expired dispatches move to `RECONCILIATION_REQUIRED` with audit evidence; they are not put back in the approved queue and are never blindly re-dispatched.
- Added response-shape, argument validation, error redaction, SQL invariant, and CLI guardrail tests plus release-gate checks.
- No new migration added; this uses `0021_controlled_replay_dispatch.sql`.
- Live Supabase/PostgreSQL behavior and provider sandbox outcomes remain unverified; production outbound and payments remain disabled.

## v43 — Staging Evidence Integrity

- CLI verification now requires an evidence root and verifies that each referenced artifact exists, is non-empty, is not reached through symlinks or path traversal, and matches its declared SHA-256.
- Added tests for tampering, missing files, path traversal, symlinks and empty evidence.
- This validates local artifact integrity only; staging/provider behavior still needs live evidence.

## MVP v44 — Live staging concurrency probe (opt-in)

- Added `scripts/staging_concurrent_replay_claim.py` to race two real Supabase RPC claims against one disposable, approved replay fixture.
- Requires explicit `--execute`, `--confirm-disposable-fixture`, explicit `APP_ENV=staging`, HTTPS project URL, server-side service-role key, and valid tenant/request UUIDs.
- The probe never invokes an external provider. Any winning claim is finished as `OUTCOME_UNKNOWN` so the fixture goes to reconciliation rather than back to the execution queue.
- Reports do not include secrets or raw exception text; cleanup failures are surfaced as generic error codes and require operator follow-up.
- Added deterministic tests for the exactly-one-winner invariant and release-gate coverage. This build has not run the probe against a real staging instance because staging credentials/fixture were not supplied.

## MVP v45 — Staging security acceptance

- Added `scripts/staging_security_acceptance.py` to combine the existing read-only two-user tenant-isolation probe with evidence from the separately executed v44 concurrent-claim probe.
- Acceptance fails closed if tenant checks fail, the concurrency report is missing, there are not exactly two attempts and one winner, the provider-called flag is not false, or cleanup evidence is absent/incomplete.
- The combined report stores the concurrency report's SHA-256 rather than copying its worker details. It does not call providers or execute the mutating concurrency probe.
- Added strict schema and fail-closed tests and release-gate coverage.
- Local tests validate the acceptance logic only. Live Supabase RLS/concurrency and provider sandbox validation remain pending; this is not a security certification.

## v46 — Staging evidence freshness and identity

- Tightened the concurrency-evidence verifier to require timezone-aware evidence timestamps within a 24-hour window (with a five-minute future tolerance).
- Requires UUID-shaped organization and replay fixture IDs, distinct worker identities, no worker errors, and a known reconciliation cleanup status.
- Expanded the static release gate and added regression tests for stale/naive timestamps, invalid fixture IDs, duplicate worker IDs, and invalid cleanup outcomes.
- This is local validation hardening only; it does not mean a real Supabase staging probe has been executed.

## v47 — Signed staging evidence
- Added HMAC-SHA256 envelope signing and verification for staging JSON reports.
- Enforces a minimum 32-byte shared secret and constant-time signature comparison.
- Documents key handling and explicitly limits claims: signatures establish integrity for key holders, not truth of test results or launch readiness.
- Adds five focused unit tests and a release-gate check.

## MVP v48 — Real-estate commercial golden-path simulation

- Added an offline real-estate lead journey: deterministic scoring, contact-permission guards, simulated follow-up/visit actions, audit events, and machine-readable JSON reports.
- Added mandatory human-review routing for discounts above 10%, custom contracts, legal questions, serious complaints, and strategic-client cases.
- Added tenant mismatch and automation kill-switch fail-closed behavior, unknown-input rejection, and stable in-memory action idempotency.
- Added a three-lead example fixture, runnable CLI, tests, and static release-gate coverage.
- Every action explicitly declares `external_side_effect: false`; the simulator does not contact providers, write CRM/calendar records, or take payments.
- Local simulation only. No live Supabase/Postgres, CRM, WhatsApp, email, calendar or payment provider was tested; live actions remain disabled.


## MVP v49 — real-estate lead persistence

- Added a durable local SQLite repository for tenant-scoped lead snapshots, optimistic versions, idempotency and append-only audit events.
- Added a PostgreSQL/Supabase migration with composite tenant keys, RLS enabled and direct client-role privileges revoked.
- Added a persistence rehearsal CLI that runs the offline real-estate journey and saves the results without network/provider side effects.
- Added tests for database reopen, tenant isolation, same-key deduplication, conflicting idempotency reuse, optimistic version conflicts, event history and concurrent duplicate submissions.
- Hosted staging has not been contacted; migration 0022 is prepared but unapplied. SQLite is not a production multi-host database. Live outbound and payments remain disabled.


## MVP v50 — Operational lead API

- Added authenticated tenant-scoped lead create/update, list, read, and event timeline endpoints to the existing FastAPI app.
- API writes require an `Idempotency-Key`; optional expected-version checks prevent lost updates.
- Added integration tests for authentication, persistence/readback, audit event visibility, idempotent replay, tenant isolation, optimistic concurrency conflicts, and fail-closed production adapter behavior.
- The API uses the existing SQLite durable adapter in local/pilot mode only. `APP_ENV=production` explicitly refuses a local SQLite fallback until a hosted PostgreSQL/Supabase lead adapter is implemented.
- Validation performed locally: 341 tests passed; compile, RPC contract, static release gate, and ZIP integrity checks must be rerun at packaging time.
- No live Supabase, PostgreSQL staging, or provider integration was accessed. Outbound messaging and payments remain unchanged and disabled pending staging acceptance.


## v52
- Added migration `0024_operational_lead_concurrency.sql` to serialize concurrent first writes and idempotency-key claims using transaction-scoped advisory locks.
- Normalized PostgREST unique-violation and serialization-failure responses into `LeadConflict` so callers receive a stable 409 API response.
- Added regression tests for conflict mapping, migration lock ordering, and release-gate coverage.
- Live Supabase staging was not available; remote behavior remains unverified.

## v53 — Staging acceptance evidence verifier
- Added fail-closed verifier for operator-collected staging evidence with 24-hour freshness, two-organization requirement, concurrency/idempotency checks, disabled live-action assertions, and credential-field rejection.
- Added regression tests and static release-gate enforcement.
- No remote staging validation was performed; evidence example is explicitly illustrative.

## v55 — Read-only live staging probe

Added `scripts/staging_readonly_probe_v55.py`, an environment-configured, HTTPS-only, read-only probe that checks API health, each test user's access to its own existing lead, and reciprocal cross-tenant denial. It never creates or updates leads and never prints bearer tokens. Configure the seven `STAGING_*` variables described in `STAGING_PROBE_V55.md`. Live probe was not run without staging credentials.
\n\n## v56 — Automated CI and staging acceptance\n\nAdded `.github/workflows/staging-acceptance-v56.yml`: static quality checks run on pushes and pull requests; a manually dispatched job runs the read-only v55 staging tenant-isolation probe only after static checks pass, then uploads a sanitized JSON report. See `CI_STAGING_ACCEPTANCE_V56.md`. Live staging remains unverified until GitHub Environment secrets are configured and the workflow is run against the actual staging API.\n\n\n## v57 — Production promotion safety gate\n\nAdded `scripts/verify_production_promotion_v57.py`, which requires signed, fresh staging evidence, valid semantic acceptance checks, and explicit disabled settings for live outbound messaging and payments. This is a fail-closed decision gate only; it does not deploy or authorize production automatically. See `PRODUCTION_PROMOTION_GATE_V57.md`.\n\n## v58 — Release artifact binding\n\n- Added fail-closed promotion verifier binding signed staging evidence to a full Git commit SHA and the SHA-256 of the exact artifact.\n- Added six regression tests for matching/mismatching/missing bindings and tampered evidence.\n- No automatic deployment; remote staging remains unverified. See `RELEASE_ARTIFACT_BINDING_V58.md`.\n\n\n## v59 — CI release provenance\n- Added CI-generated source ZIP and SHA-256 provenance manifest tied to the exact Git commit and run ID.\n- Release artifact job runs only after static quality passes and only on main/master pushes.\n- No automatic deployment; provenance is not staging acceptance evidence.\n\n\n## v60 — Commercial intake and first revenue funnel\n\n- Added Portuguese `/offer` landing page for the real-estate agency service.\n- Added durable public demo-request intake, idempotency, honeypot, consent and basic per-email rate limiting.\n- Added token-protected internal queue and lead-status workflow.\n- Added nine local tests. No live payments, outbound messaging, deployment or remote Supabase validation is claimed.\n