# v56 — Automated CI and staging acceptance

## What is automated

`.github/workflows/staging-acceptance-v56.yml` runs the static quality gate on pushes and pull requests:
- Python compilation
- complete pytest suite
- RPC contract checks
- static release gate

A manually dispatched workflow (`workflow_dispatch`) also runs the v55 **read-only** tenant-isolation probe against the configured staging environment. It makes GET requests only and uploads the sanitized JSON report as a 14-day artifact. The live staging job runs only after the static job passes.

## Configure GitHub

Create a GitHub Environment named `staging`, protect it with required reviewers if appropriate, and configure these Environment secrets:

- `STAGING_API_BASE_URL` — HTTPS URL of the staging API
- `STAGING_ORG_A`, `STAGING_ORG_B` — distinct organization IDs
- `STAGING_USER_A_TOKEN`, `STAGING_USER_B_TOKEN` — short-lived, least-privilege user tokens
- `STAGING_EXISTING_LEAD_A`, `STAGING_EXISTING_LEAD_B` — non-sensitive existing test lead IDs

Do not use service-role keys or production user tokens. Use dedicated test users and rotate short-lived tokens. The probe checks each user's own lead is readable and the other tenant's lead is denied with HTTP 403/404. The `/health` endpoint must return 200.

## Run it

1. Push this repository to GitHub with the workflow committed.
2. Configure the `staging` Environment secrets.
3. Open **Actions → AI Sales System v56 — CI and staging acceptance → Run workflow**.
4. Inspect the run and download the `staging-readonly-probe-*` artifact.

Missing secrets or network/configuration failures deliberately block the live job. The report does not contain tokens. Do not paste secrets into workflow inputs, commit `.env` files, or expose report artifacts publicly.

## Scope and release policy

This is a CI pipeline and read-only authorization probe, not a full staging certification. It does not apply migrations, test concurrent database writes, send messages, create calendar events, or charge payments. The probe validates HTTP authorization behavior through the deployed API; it does not independently prove every database RLS policy. Production promotion remains blocked until migrations, database/RLS, concurrency, provider sandboxes, rollback, monitoring, and operational approvals have been tested separately.

## Local reproduction

```bash
python -m compileall -q app scripts tests
python -m pytest -q
python scripts/check_rpc_contracts.py
python scripts/release_gate.py --static-only
```
