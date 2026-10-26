# v53 — Staging acceptance evidence verifier

## Goal
Make staging acceptance repeatable and fail-closed. This release does **not** claim that remote staging was run; it adds a verifier for evidence collected by an operator against the dedicated staging project.

## Required evidence
Create a JSON file from actual results using this schema (replace all example values):

```json
{
  "schema_version": 1,
  "project_ref": "abcdefghijklmnopqrst",
  "captured_at": "2026-10-21T12:00:00Z",
  "organization_a": "staging-org-a",
  "organization_b": "staging-org-b",
  "operator": "operator-label",
  "live_outbound_enabled": false,
  "live_payments_enabled": false,
  "checks": {
    "auth_user_a": true,
    "auth_user_b": true,
    "tenant_isolation_a_to_b": true,
    "tenant_isolation_b_to_a": true,
    "same_key_replay": true,
    "concurrent_first_write": true,
    "stale_version_conflict": true,
    "migration_0024_applied": true,
    "live_actions_disabled": true
  }
}
```

The values above are illustrative, **not real test results**. Do not mark a check true unless its test was executed and observed. Never put JWTs, passwords, API keys, or tokens in this evidence file.

## Run
1. Apply SQL migrations through `0024_operational_lead_concurrency.sql` in a dedicated staging project.
2. Run the read-only connectivity and tenant probes:
   - `APP_ENV=staging python scripts/staging_smoke.py`
   - `APP_ENV=staging python scripts/staging_tenant_isolation.py`
3. Run concurrency and adapter regression tests locally: `pytest -q tests/test_v52_lead_concurrency.py tests/test_v51_supabase_lead_adapter.py`.
4. Execute same-key replay, concurrent first-write, stale-version and migration verification using two separate staging users in distinct organizations. Record only outcomes in the JSON evidence.
5. Verify evidence: `python scripts/verify_staging_acceptance_v53.py staging-evidence.json --report STAGING_ACCEPTANCE_RESULT.md`.
6. Require the verifier to return exit code `0` before declaring staging accepted.

## Fail-closed rules
- Evidence older than 24 hours, future-dated evidence, missing checks, failed checks, same organization IDs, or enabled live actions blocks acceptance.
- Credential-like fields are rejected to prevent accidental secret retention.
- The report includes only project reference, timestamp and status, not authentication material.
- The verifier makes no network calls and cannot independently prove that the operator's claims are true; retain raw test logs securely outside the evidence JSON.

## Scope and limitation
This version provides evidence validation, not a remote test executor. No staging credentials were available during the build, so there is no live Supabase acceptance result. Keep live outbound messages, calendar actions and payments disabled until the relevant provider sandbox and business-flow acceptance tests pass.
