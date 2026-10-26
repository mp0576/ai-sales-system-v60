# MVP v41 — replay concurrency and crash-window tests

## Purpose

v41 adds deterministic tests for two operational hazards: two workers racing to
claim the same approved replay, and a provider applying a side effect while its
response is lost. It also verifies that a persistence failure after execution is
never reported as a successful completed replay.

## Run

```bash
python -m pytest -q tests/test_v41_replay_concurrency.py
```

## Expected invariants

- Two competing workers produce at most one executor invocation for a single
  atomic claim.
- The original idempotency key is preserved.
- An ambiguous provider outcome is marked for reconciliation, not automatic
  replay.
- A finish/persistence failure does not become a success response.

## Evidence boundary

These tests use a thread-safe in-memory store. They validate the dispatcher
contract and failure handling, not PostgreSQL locking, Supabase RLS, or a real
provider's idempotency implementation. The live staging acceptance checks remain
blocked until the same race is tested against the deployed RPC with two separate
clients and provider sandbox evidence is collected. Do not mark the staging
manifest PASS based on these local tests alone.
