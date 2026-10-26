# v45 — Staging security acceptance

## Purpose

Combine two independent evidence sources: (1) read-only tenant-isolation requests using two staging user JWTs, and (2) the JSON report produced by the opt-in v44 concurrent replay-claim probe. The command fails closed if either source is missing or invalid.

## Required configuration

Set `APP_ENV=staging`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `STAGING_USER_A_JWT`, `STAGING_USER_A_ORG_ID`, `STAGING_USER_B_JWT`, and `STAGING_USER_B_ORG_ID`. The two users must belong to different organizations and have valid JWTs for the staging project.

Run the concurrency probe separately against a disposable approved replay request, following `STAGING_REPLAY_CONCURRENCY_V44.md` and its explicit confirmation requirements. Never use a real customer request.

## Command

```bash
APP_ENV=staging python scripts/staging_security_acceptance.py \
  --concurrency-report staging-concurrency-probe.json \
  --output staging-security-acceptance.json
```

The command performs only GET requests for tenant isolation. It does not perform writes, call an external provider, or re-run the mutating concurrency probe. The report contains the SHA-256 of the concurrency report rather than copying its contents.

## Decision semantics

- `PASS`: both tenant-isolation checks and the supplied concurrency evidence meet the implemented checks.
- `NO_GO`: a required source is absent, any tenant check fails, the concurrency invariant is not exactly one winner from two workers, or cleanup evidence is missing/incomplete.

A report hash proves byte integrity relative to the file that was read, not authenticity of the test execution. Review logs and the referenced source report. This is not a security certification and does not establish provider idempotency, full RLS coverage, or production readiness.
