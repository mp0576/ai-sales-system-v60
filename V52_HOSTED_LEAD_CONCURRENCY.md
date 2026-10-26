# v52 — Hosted lead-write concurrency

## Why
In v51, `SELECT ... FOR UPDATE` cannot lock a snapshot row before that row exists. Two concurrent first writes for the same lead can therefore race on the primary key. A concurrent reuse of an idempotency key can also race before an idempotency row exists.

## Changes
- Migration `0024_operational_lead_concurrency.sql` replaces the v51 RPC and acquires transaction-scoped advisory locks in a stable order: organization + idempotency key, then organization + lead.
- Tenant membership is still checked through `auth.uid()` before writes; the function retains `SECURITY DEFINER`, fixed `search_path`, and authenticated-only execute grant.
- Supabase adapter maps SQLSTATE `23505` (unique violation), `40001` (serialization failure), and recognized idempotency/version conflicts to `LeadConflict`, allowing the API to return HTTP 409 rather than a generic server error.
- Release gate now requires migration 0024 and the migration guide documents application order.

## Deployment
1. Back up the dedicated staging project and apply migrations through `0024` in numeric order.
2. Verify the final RPC definition and grants in the Supabase SQL editor.
3. Run `pytest -q tests/test_v52_lead_concurrency.py tests/test_v51_supabase_lead_adapter.py`.
4. With two valid staging sessions, run concurrent first writes for the same lead and same idempotency key; verify one logical version/event, consistent replay, and a stable 409 for conflicting reuse.
5. Repeat across two organizations and verify no cross-tenant reads or writes.

## Limits
No remote Supabase credentials were available for this build. Local tests and static SQL checks do not prove actual PostgreSQL lock behavior, RLS grants, or staging tenant isolation. Keep live outbound messaging, calendar booking, and payment execution disabled until separate integration acceptance is complete.
