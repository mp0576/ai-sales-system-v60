# MVP v36 — audited exception replay approvals

## What changed

- Added migration `0020_audited_replay_approvals.sql` with a tenant-scoped replay-request ledger and append-only audit trail.
- Replay requests are accepted only for an allowlisted transient failure, a confirmed `NOT_APPLIED` external outcome, an exception in an eligible state, a bounded replay number (1–10), and the original stable idempotency key.
- A unique `(organization_id, exception_id, replay_number)` constraint and row locks prevent duplicate concurrent requests for the same replay slot.
- A manager can approve or reject a pending request; the requester cannot approve their own request. Every request and decision is audited with an actor and reason.
- Python repository methods call the trusted-backend RPCs and validate inputs before making the request. Provider error bodies are not copied into raised errors.

## Important limitation

**Approval is not execution. There is no provider dispatch in this version.** The migration records a durable request and decision only. It does not enqueue an outbox event, invoke a provider, or run a replay worker. A later version must add a separately authorized dispatcher that rechecks the current exception, approval, lease, budget and idempotency key atomically before dispatch. Unknown provider outcomes, payment reconciliation, invalid webhook signatures and other sensitive categories must remain outside replay.

## Rollout and validation

1. Back up a dedicated staging project and apply migrations in numeric order through `0020_audited_replay_approvals.sql`.
2. Run `python scripts/check_rpc_contracts.py` and `python scripts/release_gate.py --static-only`.
3. Verify tenant isolation, role membership, requester/approver separation, concurrent requests, replay slot uniqueness and audit rows in staging.
4. Do not enable live outbound or payments based on local tests. No live Supabase or provider sandbox was contacted for this release.
