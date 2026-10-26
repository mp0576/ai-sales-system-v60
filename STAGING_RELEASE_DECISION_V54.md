# v54 — Signed staging release decision

## Purpose

v53 validated the shape and freshness of operator-collected staging evidence, while the existing HMAC helper only verified file integrity. v54 combines both gates: a signed envelope must first pass HMAC-SHA256 verification and its embedded evidence must then pass every v53 semantic acceptance rule.

## Run

1. Execute staging checks against a dedicated Supabase staging project and record only results, never tokens or passwords, in the evidence JSON described in `STAGING_ACCEPTANCE_V53.md`.
2. Set `STAGING_EVIDENCE_HMAC_KEY` to a random secret of at least 32 bytes. Keep it out of source control and evidence files.
3. Sign the evidence:
   `python scripts/sign_staging_evidence.py staging-evidence.json --output staging-evidence.signed.json`
4. Verify both signature and acceptance policy:
   `python scripts/verify_staging_release_v54.py staging-evidence.signed.json --report STAGING_RELEASE_DECISION.md`
5. Require exit code `0` before recording staging acceptance. Exit `1` means evidence/policy failure; exit `2` means an input or key error.

## Security properties and limitations

- Signature is checked before semantic validation. A modified envelope fails closed.
- A valid signature does not override stale evidence, failed checks, missing checks, credential fields, tenant mismatch, or enabled live actions.
- HMAC proves integrity for holders of the shared key; it does not identify a specific operator or independently prove tests ran. Restrict key access and retain raw logs securely.
- The script performs no network calls and does not execute staging tests. No remote staging environment was accessed while building v54.
- Live outbound messages and payments must remain disabled until remote staging and provider sandbox acceptance are complete.
