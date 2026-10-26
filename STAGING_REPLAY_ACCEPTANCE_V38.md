# v38 — Staging replay acceptance runbook

## Purpose and scope

This release adds a repeatable, read-only catalog acceptance probe and a fail-closed CSV evaluator for migrations `0020` and `0021`. It does not apply migrations, create test records, call provider APIs, or enable live actions. It is not a substitute for operational testing.

## Gate A — catalog and privileges

1. Use a dedicated disposable Supabase staging project; verify `APP_ENV=staging` and both live-action flags are false.
2. Apply migrations in order through `0021_controlled_replay_dispatch.sql` using the normal migration process.
3. Run `sql/staging_replay_dispatch_acceptance.sql` as a database administrator. Export the result grid as CSV with `check_name,result,detail` columns.
4. Run `python scripts/verify_staging_acceptance.py <export.csv>`. Any missing row, duplicate, failed privilege, absent column, or incomplete export is NO-GO.
5. Save the CSV and command output as release evidence; redact project identifiers if shared outside the operators.

## Gate B — operational rehearsal (manual, no production providers)

Use two dedicated test organizations and a mock/sandbox provider that supports idempotency keys. Do not use customer data or real payment methods.

- [ ] Tenant A cannot claim, inspect, or finish Tenant B's replay request.
- [ ] Two workers race to claim the same approved request; exactly one receives a claim.
- [ ] A rejected, pending, or unapproved request never reaches the executor.
- [ ] The original idempotency key is unchanged across provider retries and logs contain no secret/payload.
- [ ] A simulated provider timeout after acceptance becomes `RECONCILIATION_REQUIRED`, not an immediate replay.
- [ ] A worker killed after claim is reconciled after lease expiry; it is not auto-claimed again.
- [ ] A finish RPC failure is visible as ambiguous and requires reconciliation.
- [ ] Audit evidence exists for request, decision, claim, finish/reconciliation.
- [ ] Outbound messaging and live payments remain disabled.

Record each test as PASS/FAIL with timestamp, environment, build identifier, and operator. Any failure or unexecuted mandatory test means NO-GO. Do not paste JWTs, service-role keys, customer data, or provider secrets into the evidence file.

## What a PASS means

A passing CSV evaluator means the expected database objects and privilege boundaries are visible in staging. Only a completed Gate B supports a staging operational acceptance decision. Neither gate is production certification; production launch remains blocked until separately reviewed.
