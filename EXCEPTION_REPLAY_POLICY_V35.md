# v35 — Controlled exception replay policy

This release adds a **read-only decision planner**, not an automatic replay executor.
It reduces unsafe retries by failing closed unless the failure is explicitly allowlisted,
the external operation is confirmed **not applied**, a stable existing idempotency key
is present, the exception is OPEN/ACKNOWLEDGED, and the bounded replay budget remains.

## Decisions

- `REPLAY_PLAN`: transient allowlisted failure, known not applied, stable key, budget remains. Preserve the exact original idempotency key; do not dispatch automatically.
- `RECONCILE`: provider outcome unknown, payment reconciliation, invalid webhook signature, or human-approval exception. Verify provider/ledger state first.
- `APPROVAL_REQUIRED`: explicitly marked for approval.
- `HOLD`: missing evidence, unsupported failure class, invalid state, missing key, or exhausted budget.

Sensitive codes take precedence over generic replay eligibility. The default replay budget is three, configurable from 1 to 10. This is an advisory plan only; a trusted service must re-check tenant authorization, persist an audit record, enforce concurrency/idempotency, and separately authorize dispatch before any replay.

## Read-only CLI

`python scripts/exception_replay_plan.py exceptions.json --max-replays 3`

Input is a JSON array of exception/action objects. Output contains generic decision codes and explicitly states `execute: false`. The tool does not connect to a database, mutate an exception, enqueue work, or call a provider. Avoid including personal data or raw provider diagnostics in input files.

## Validation boundary

Unit tests cover sensitive outcomes, bounded budgets, stable idempotency keys, status checks, and read-only CLI behavior. These are local tests; no live Supabase database, provider sandbox, or real replay was exercised. Live outbound and payment flags must remain disabled until staging reconciliation, authorization, audit, and concurrency controls are validated.
