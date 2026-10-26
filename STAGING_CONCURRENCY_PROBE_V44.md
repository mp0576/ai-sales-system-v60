# Staging concurrency probe — v44

This probe performs one real database test: two concurrent backend calls attempt to claim the **same approved replay request**. It never invokes a provider or the replay executor.

## Safety requirements

- Use a dedicated Supabase **staging** project and a disposable replay-request fixture approved specifically for this test.
- The probe changes fixture state. A winning claim is finished with `OUTCOME_UNKNOWN`, which routes it to `RECONCILIATION_REQUIRED`; it is not returned to the queue.
- If cleanup fails or the HTTP response is lost, inspect the fixture and use the existing expired-lease reconciliation procedure. Never assume the probe left no state behind.
- Use the trusted backend service-role credential only in a protected shell/secret manager. The script never prints the credential or provider/DB exception text.
- Do not run against production or a business-critical request.

## Configure

Set the following in the staging worker environment:

- `APP_ENV=staging` (must be explicitly set)
- `SUPABASE_URL=https://<staging-project>.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` (server-side only)
- `STAGING_PROBE_ORGANIZATION_ID=<UUID>`
- `STAGING_PROBE_REPLAY_REQUEST_ID=<UUID>` (a disposable, currently `APPROVED` request belonging to that organization)

## Execute explicitly

```bash
python scripts/staging_concurrent_replay_claim.py \
  --execute \
  --confirm-disposable-fixture \
  --output staging-concurrency-probe.json
```

Expected result: exactly one of the two concurrent claim RPCs returns a row, and the winning worker is finished as `OUTCOME_UNKNOWN`. The JSON report records only IDs, worker labels, status and generic error types; it contains no secret values. A passing claim invariant is not a production launch approval.

## Interpretation

- `PASS`: exactly one worker won the atomic claim race. Review cleanup status and the audit trail in staging before accepting the test.
- `FAIL`: zero or two winners, or an RPC error. Preserve the report and inspect the staging fixture and SQL logs.
- This validates the deployed RPC under one race only. It does not prove provider idempotency, full RLS isolation, or all crash windows.
