# v58 — Bind staging evidence to release artifact

The v58 gate extends the v57 fail-closed promotion decision. The signed staging report must include:
- `source_commit`: full 40-character Git commit SHA tested in staging.
- `artifact_sha256`: SHA-256 of the exact release artifact tested in staging.

At promotion time, operators must supply the intended commit and the artifact file. The gate hashes the artifact itself and requires exact matches to the signed report. Missing values, malformed hashes, changed evidence, stale/failed v57 evidence, or enabled live actions block the decision.

```bash
export STAGING_EVIDENCE_HMAC_KEY='use-a-secret-of-at-least-32-bytes'
python scripts/verify_production_promotion_v58.py staging-evidence.signed.json \
  --expected-commit FULL_40_CHARACTER_GIT_SHA \
  --artifact dist/ai-sales-system.zip \
  --report promotion-decision.json
```

A successful result is only `ELIGIBLE_FOR_MANUAL_REVIEW`; the script never deploys. The evidence producer must record the actual commit and artifact digest **before signing**. Do not edit signed evidence after tests. HMAC integrity is not independent proof that tests genuinely ran. No remote staging or deployment was performed by this change.
