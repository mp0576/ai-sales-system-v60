# v34 — Worker-to-exception-center integration

## Behavior

- The durable worker can receive an optional trusted-backend `exception_store`.
- Permanent dispatcher/handler failures are first committed to the outbox as `DEAD_LETTER`; only then does the worker attempt to create a tenant-scoped `DEAD_LETTER` exception.
- Unexpected failures retry with backoff while the configured attempt budget remains. At `attempts >= max_attempts`, the worker marks the outbox item permanently failed and records the same exception type.
- Exception creation uses the existing database uniqueness key `(organization_id, source_type, source_id)` via the v33 RPC. Repeated attempts are therefore idempotent at the database layer.
- Summaries are static and generic. Payloads, contact data, raw provider responses, and exception text are never passed to the exception store.
- Failure to persist the exception does not misreport the outbox item as successful; the result includes `exception_errors` for monitoring.
- If the worker cannot finish an item because its lease was lost, it does not create an exception: it no longer owns the outcome.

## Configuration

Construct `DurableWorkerService(..., exception_store=SupabaseOperationalExceptionStore(...))` only in trusted backend code with a server-only service-role credential. Leaving `exception_store=None` preserves the existing local/runtime behavior and summary shape.

## Validation

Run:

```bash
pytest -q tests/test_v34_worker_exception_integration.py
pytest -q
python scripts/check_rpc_contracts.py
python scripts/release_gate.py --static-only
```

Tests use deterministic fakes. They validate application wiring and retry-budget behavior, not PostgreSQL transactionality, remote RPC grants, actual worker leases, or provider behavior. Before pilot use, apply migrations through `0019_durable_exception_center.sql` in a disposable Supabase staging project and test dead-letter transitions with two worker processes and forced database outages. Keep `OUTBOUND_ENABLED=false` and `ENABLE_LIVE_PAYMENTS=false` until staging evidence is reviewed.
