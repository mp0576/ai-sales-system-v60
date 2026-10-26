# MVP v32 — Exception Center & Resolution Workflow

## Purpose

The exception center collects operational cases that should not be retried blindly: unknown provider outcomes, failed actions, rejected webhook signatures, pending human approvals, payment reconciliation cases, and dead-lettered work. It creates a tenant-scoped, privacy-minimized queue from exported JSONL events.

## Generate a queue (read-only)

```bash
python scripts/exception_queue.py events.jsonl --organization-id agency-demo
```

Each input line must be a JSON object containing `organization_id`, `type`, a stable `event_id` (or `id`), and an ISO timestamp with timezone. Malformed JSON aborts the command without a partial report. Events from other organizations are ignored. Unknown event types are ignored. The output contains generic labels and does not copy names, emails, phone numbers, message bodies, or raw provider errors.

## Lifecycle and permissions

- `OPEN` → `ACKNOWLEDGED` → `RESOLVED`, or `OPEN`/`ACKNOWLEDGED` → `DISMISSED`.
- `assign` is allowed only before a terminal state.
- Only `OWNER`, `ADMIN`, and `MANAGER` roles may assign, acknowledge, resolve, or dismiss. These are the manager-level roles.
- Resolution/dismissal requires a bounded note; never put customer secrets or full message bodies in the note.
- Cross-organization access is denied. Every caller must authenticate the actor and obtain the organization scope from trusted server-side membership, not from an untrusted request body.

## Idempotency and persistence

The queue is idempotent for repeated source events. Queue IDs are deterministic for `(organization_id, source_event_id, exception_code)`. The function deduplicates repeats within one export; durable idempotency requires the eventual repository to enforce a unique `(organization_id, exception_id)` constraint. `transition_exception` validates and returns a copy only. A production API must persist the state transition and append an audit record atomically, enforce optimistic concurrency/row locking, and re-check membership in the database transaction.

## Limitations and launch guardrails

**Live persistence is not implemented in v32.** This is a local domain layer and read-only JSONL CLI, not a deployed dashboard/API, notification service, or durable queue. Role checks here are defense-in-depth and do not replace authenticated server-side authorization or database RLS. No notifications are sent and no event is replayed automatically. Keep live outbound and payments disabled until staging tests prove tenant isolation, atomic audit persistence, concurrent updates, and provider reconciliation.

## Acceptance checklist

- [ ] Apply and test the durable exception table and transition RPCs in disposable staging.
- [ ] Prove cross-tenant reads and mutations are denied with real user accounts.
- [ ] Test concurrent acknowledge/resolve attempts and audit atomicity.
- [ ] Verify alerts contain no contact PII or provider secrets.
- [ ] Confirm unknown provider outcomes require reconciliation before retry.
- [ ] Keep outbound messaging and live payments disabled until all blockers are evidenced.
