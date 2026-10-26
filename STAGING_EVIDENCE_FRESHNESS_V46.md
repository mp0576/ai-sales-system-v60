# v46 — Freshness and identity checks for staging evidence

The security-acceptance verifier now rejects concurrency reports unless they include a timezone-aware `observed_at` timestamp no older than 24 hours (and no more than five minutes in the future), valid UUIDs for the staging organization and disposable replay fixture, two distinct worker identifiers, no worker error codes, exactly one winner, and a successful transition of that winner to a reconciliation state.

Run the read-only acceptance verifier only after producing the concurrency report separately:

```bash
APP_ENV=staging python scripts/staging_security_acceptance.py \
  --concurrency-report staging-concurrency-probe.json \
  --output staging-security-acceptance.json
```

This command performs read-only tenant-isolation requests and validates the report. It does not run the mutating concurrency probe or contact an external provider. The report timestamp and UUIDs improve freshness and fixture integrity checks, but they do not cryptographically prove the report's origin. Store the evidence directory with restricted write access and review the report before authorizing any pilot.

A `PASS` is not a security certification and does not establish provider idempotency, production readiness, or successful remote execution unless the underlying probes were genuinely run against the intended staging environment.
