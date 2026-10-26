# v51 — Hosted operational lead storage

## What changed
- Production lead API now selects `SupabaseLeadRepository` using the authenticated caller's Supabase JWT.
- New migration `sql/migrations/0023_operational_lead_api.sql` adds tenant-scoped snapshots, idempotency ledger and append-only event history.
- Atomic snapshot + event + idempotency write runs in one PostgreSQL RPC transaction.
- RLS limits reads to organization members; direct client writes are revoked. RPC checks `auth.uid()` and membership.
- Local/pilot mode retains SQLite persistence. Production mode refuses fallback if no authenticated principal is available.
- RPC signature is checked by `scripts/check_rpc_contracts.py`.

## Configure and validate
1. Apply migrations 0001–0023 in order to a dedicated Supabase staging project.
2. Ensure `SUPABASE_URL` and `SUPABASE_ANON_KEY` are configured in the API environment. The per-request access token is forwarded from the authenticated user; **do not set or use a service-role key** in this adapter.
3. Verify `organization_id` values are UUIDs matching `organizations.id`.
4. Run the test suite and `python scripts/release_gate.py --static-only`.
5. In staging, test two organizations and two users: member access, non-member denial, idempotent replay, conflicting replay, stale version and concurrent first-write behavior.

## Important limitations
- This build was validated locally only. No live Supabase project, migrations, grants, RLS behavior, or remote concurrency was tested in v51.
- The write RPC uses `SECURITY DEFINER` so it can perform atomic writes despite direct client write grants being revoked; it explicitly checks `auth.uid()` membership, fixes `search_path`, and is executable only by `authenticated`. Review this function carefully during staging security acceptance.
- Concurrent first writes for the same lead can produce a PostgreSQL conflict; callers should retry only after inspecting the resulting state and reuse the same idempotency key.
- Provider messaging, calendar bookings and payment execution remain outside this API.
