# v39 — Operational staging rehearsal evidence

## Purpose

Collect a reproducible evidence manifest for the operational rehearsal described in `STAGING_REPLAY_ACCEPTANCE_V38.md`. The verifier is offline-only: it does not connect to Supabase, inspect artifact contents, run workers, or call providers. It validates completeness, safe relative artifact references, timestamps, and SHA-256 digest formatting.

## Required evidence

Create a JSON manifest following `templates/staging_rehearsal_evidence.example.json`. The required checks are:

- `tenant_isolation` — two staging organizations cannot read or mutate each other's records.
- `concurrent_claim_single_winner` — competing workers produce exactly one successful claim.
- `provider_idempotency_duplicate_suppressed` — the sandbox confirms a duplicate request using the original idempotency key does not create a second operation.
- `unknown_outcome_reconciliation` — an ambiguous provider result is held for reconciliation, not automatically resent.
- `expired_lease_no_redispatch` — expired dispatch lease is not automatically redispatched.
- `audit_trail_complete` — request, decision, claim, and outcome are traceable without exposing credentials or unnecessary PII.
- `live_actions_disabled` — outbound production messaging and live payments remain disabled.

For every check, attach a relative `evidence_ref`, the SHA-256 digest of that artifact, a `PASS` result, and UTC `observed_at`. Keep artifacts in a controlled staging evidence store; do not put credentials, tokens, full payment data, or unnecessary personal data in the manifest or evidence package. The verifier does not read the referenced artifact and does not calculate its digest for you.

## Verify

```bash
python scripts/verify_staging_rehearsal.py rehearsal-manifest.json --report rehearsal-report.json
```

Exit code `0` means only that the manifest is complete enough for manual review. Exit code `1` means a failed or incomplete manifest; exit code `2` means input/output could not be processed. A report decision of `GO_FOR_MANUAL_REVIEW` is **not launch authorization**. An operator must open and inspect every referenced artifact, verify each digest against the artifact bytes, and sign off separately.

## Release rule

Any missing check, non-PASS result, duplicate check name, invalid digest format, unsafe path, or non-UTC timestamp is NO-GO. If a test cannot be run, record it as `BLOCKED` and keep the pilot blocked. Do not fabricate evidence or mark an unrun check as passed.

Live outbound and payments must remain disabled during the rehearsal. The evidence manifest is not proof that the underlying events occurred, nor a substitute for actual two-tenant tests, concurrent worker tests, database permission checks, or provider sandbox results.
