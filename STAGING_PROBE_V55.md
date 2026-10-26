# v55 — Read-only staging probe

This probe makes live HTTPS GET requests only. It does not write data, does not print access tokens, and fails closed.

## Run

Provide environment variables in your secure shell/CI secret store (never commit them):
- `STAGING_API_BASE_URL` — HTTPS API base URL
- `STAGING_ORG_A`, `STAGING_ORG_B` — different organization IDs
- `STAGING_USER_A_TOKEN`, `STAGING_USER_B_TOKEN` — short-lived user access tokens
- `STAGING_EXISTING_LEAD_A`, `STAGING_EXISTING_LEAD_B` — existing non-sensitive test lead IDs, each owned by its matching organization

Run `python scripts/staging_readonly_probe_v55.py`. Exit 0 means all five checks passed, 1 means an HTTP status failed policy, and 2 means configuration/network errors. A cross-tenant read is considered denied only for HTTP 403 or 404. Each user's own lead must return HTTP 200. The probe intentionally requires HTTPS.

## Limits

This checks current API reachability and read authorization only. It does not verify writes, concurrent transactions, database migration state, provider integrations, or prove the identity of the operator. Retain the output as supporting evidence, then run the signed v54 evidence/acceptance workflow. Do not enable live messages or payments based on this probe alone.
