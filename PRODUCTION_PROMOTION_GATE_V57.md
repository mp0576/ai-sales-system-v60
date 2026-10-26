# v57 — Production promotion gate

This is a **decision gate only**. It does not deploy code, enable outbound messaging, or enable live payments.

## Evaluate signed staging evidence

1. Collect real staging evidence using the v53 evidence schema, including `environment: "staging"`.
2. Sign it with the v54 signer using a shared HMAC key of at least 32 bytes. Keep the key in a secret manager; never commit it.
3. Keep both safety switches explicitly disabled.
4. Run:

```bash
export STAGING_EVIDENCE_HMAC_KEY='...'
export LIVE_OUTBOUND_ENABLED=false
export LIVE_PAYMENTS_ENABLED=false
python scripts/sign_staging_evidence.py staging-evidence.json --output staging-evidence.signed.json
python scripts/verify_production_promotion_v57.py staging-evidence.signed.json --report promotion-decision.json
```

The command returns zero only when signature, semantic staging checks, evidence freshness and safety switches pass. Its success label is `ELIGIBLE_FOR_MANUAL_REVIEW`, not production approval. It deliberately never deploys.

## Important security limitation

HMAC proves that a holder of the shared key signed the envelope and that it was not altered; it does not prove that the underlying tests truly ran. Restrict key access and require independent review of the staging run/artifact. Do not reuse a developer laptop key as a production trust root. The evidence must be freshly collected (24-hour policy) and must not contain credentials.

## Required before actual production release

- Real Supabase staging evidence, including cross-tenant access tests for both directions.
- Human review of source commit, CI run, signed evidence and migration status.
- Separate production secrets and deployment approval.
- Independent verification that outbound messaging and payments remain disabled until explicitly authorized.
- A rollback plan and monitored canary.

No remote staging or production deployment was performed while building v57.
