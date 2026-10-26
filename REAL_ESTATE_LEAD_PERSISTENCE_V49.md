# MVP v49 — Real-estate lead persistence and recovery

## What changed

- Added `SQLiteLeadRepository` for durable local development and isolated staging rehearsals.
- Stores tenant-keyed lead snapshots with optimistic version checks.
- Commits each snapshot, idempotency record, and audit event in one SQLite transaction.
- Replaying an identical idempotency key/request returns a duplicate result without another event; reusing a key for different content fails closed.
- Reads and lists always require an organization ID; all SQL lookups include the tenant key.
- Added PostgreSQL/Supabase migration `0022_real_estate_lead_persistence.sql` with tenant-composite keys, RLS enabled, client-role grants revoked, and service-role-only access.
- Added a local persistence rehearsal CLI which runs the v48 simulation and persists result snapshots without provider calls.

## Local rehearsal

```bash
python scripts/persist_real_estate_simulation.py \
  --input examples/real_estate_leads_v48.json \
  --db /tmp/real-estate-leads-v49.sqlite3 \
  --output /tmp/real-estate-leads-v49-report.json
```

The database path is explicit and local. Re-running the same input uses deterministic per-lead idempotency keys, so an identical request is not appended again. If the simulation output changes while the same key is retained, the repository rejects it; use a deliberate new event key for a new business event rather than silently overwriting history.

## Security and production boundary

- This is persistence for snapshots and event metadata, not a full production CRM integration.
- The SQLite adapter is for development/rehearsal only; do not place the file on an untrusted shared filesystem or treat it as a multi-host production database.
- The SQL migration is prepared but has **not** been applied to a live Supabase project in this release.
- `service_role` bypasses RLS. A trusted API must authenticate the user and derive/validate organization membership server-side; never trust a client-supplied organization ID without authorization.
- Audit rows have no application-level update/delete methods; hosted SQL grants deny update/delete on the event table. Database owners can still alter data, so this is not tamper-proof archival storage.
- Payload JSON may contain personal data. Minimize stored fields and apply encryption, retention, backup, access logging and deletion policies before production use.
- This release does not send WhatsApp/email, call calendars/CRMs, create payment links, or process payments.

## Local validation scope

The repository tests cover reopen/recovery, tenant-scoped queries, idempotency, conflicting keys, optimistic concurrency, append-only event behavior, parallel duplicate submissions and invalid inputs. They use local SQLite only. They do not prove PostgreSQL RLS behavior, hosted RPC grants, backup/restore, or real provider sandbox integration. Production launch remains blocked until dedicated staging evidence exists.
