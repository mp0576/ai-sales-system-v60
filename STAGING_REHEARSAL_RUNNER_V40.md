# v40 — Staging rehearsal runner

## Purpose

`python scripts/run_staging_rehearsal.py --execute --output-dir staging-rehearsal-output --run-id staging-rehearsal-2026-001`

The runner executes the repository's existing **read-only** Supabase health/table probe and two-user tenant-isolation probe. It captures stdout/stderr and exit status, hashes each artifact with SHA-256, and writes a machine-readable manifest and summary. It refuses production mode and requires explicit `--execute` before making any network request.

## Required staging environment

- `APP_ENV=staging`
- `SUPABASE_URL` (HTTPS project origin)
- `SUPABASE_SERVICE_ROLE_KEY` (backend-only secret; never commit or share)
- `SUPABASE_ANON_KEY`
- `STAGING_USER_A_JWT`, `STAGING_USER_A_ORG_ID`
- `STAGING_USER_B_JWT`, `STAGING_USER_B_ORG_ID`
- `OUTBOUND_ENABLED=false`
- `ENABLE_LIVE_PAYMENTS=false`

Use a dedicated staging project and two test users belonging to different organizations. Do not use production credentials. The service-role key is passed only to the existing read-only smoke probe and must never be placed in logs or evidence artifacts.

## Fail-closed behavior

The runner marks these checks as FAIL until dedicated live probes are implemented and executed: concurrent claim single-winner, provider idempotency, unknown-outcome reconciliation, expired-lease no-redispatch, and audit-trail completeness. It does not infer PASS from missing configuration or local unit tests. The generated manifest is a collection of evidence metadata, not a cryptographic attestation that a test is truthful. Inspect every artifact and independently validate its digest.

Run the manifest shape verifier after review:

```bash
python scripts/verify_staging_rehearsal.py staging-rehearsal-output/rehearsal-manifest.json --report staging-rehearsal-output/manifest-review.json
```

The expected result remains `NO-GO` until all required checks have real evidence. Even a complete manifest yields only `GO_FOR_MANUAL_REVIEW`, never launch authorization. No migrations are applied and no provider writes, customer messages, or live payments are attempted by this runner.
