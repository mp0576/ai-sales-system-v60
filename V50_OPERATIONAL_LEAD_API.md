# v50 — Operational lead API

## Scope
Adds authenticated API endpoints for tenant-scoped lead snapshots and audit timelines:
- `POST /api/v1/organizations/{organization_id}/leads`
- `GET /api/v1/organizations/{organization_id}/leads`
- `GET /api/v1/organizations/{organization_id}/leads/{lead_id}`
- `GET /api/v1/organizations/{organization_id}/leads/{lead_id}/events`

All routes use the existing `require_dashboard_access` authentication dependency. Requests require
`Authorization: Bearer ...`; writes additionally require an `Idempotency-Key` header of at least
8 characters. Updates support `expected_version` for optimistic concurrency. Reusing an idempotency
key with the same request is safe; reusing it with different content returns HTTP 409. Data access
is scoped by `organization_id`, and event history is append-only in the SQLite adapter.

## Local/pilot setup
Set `APP_ENV=pilot`, `DASHBOARD_API_TOKEN` to a strong token, and optionally `LEAD_DATABASE_PATH`
to a writable SQLite path. Do not commit the token or database. The default local path is
`data/real_estate_leads.sqlite3`.

Example:
```bash
export APP_ENV=pilot
export DASHBOARD_API_TOKEN='replace-with-a-long-random-secret'
export LEAD_DATABASE_PATH='./data/leads.sqlite3'
uvicorn app.dashboard.api:app --host 127.0.0.1 --port 8000
```

Example write:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/organizations/agency-a/leads \
  -H 'Authorization: Bearer replace-with-a-long-random-secret' \
  -H 'Idempotency-Key: lead-import-000001' \
  -H 'Content-Type: application/json' \
  -d '{"lead_id":"lead-123","state":"NEW","payload":{"source":"website"},"expected_version":0}'
```

## Security and deployment limits
- `APP_ENV=production` refuses to fall back to local SQLite for these endpoints. A hosted PostgreSQL/Supabase lead repository adapter must be implemented and configured first.
- In production, the existing Supabase Auth dependency validates the access token and organization membership; missing/invalid Supabase configuration fails closed.
- The local pilot bearer token is a shared development credential, not per-user identity. Use TLS and a secret manager in deployment.
- This is not a certification of hosted RLS, migrations, database concurrency on PostgreSQL, deployment hardening, or external provider integrations.
- No outbound messages, calendar events, or payments are initiated by these endpoints.
