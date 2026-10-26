# v29 — End-to-end acceptance protocol

## Purpose
This protocol validates the deterministic local sales lifecycle simulator. It is not evidence that live Supabase, WhatsApp, calendar, email, or payment providers have passed testing.

## Golden path
1. Create a lead assigned to one organization.
2. Verify research facts before contact.
3. Require valid opt-in, no do-not-contact flag, and an explicit outbound feature flag before messaging.
4. Qualify using fit, confirmed problem, high intent, budget, and decision-maker status.
5. Present the standard offer and generate a proposal at or above the configured price floor.
6. Accept only a signed, tenant-matched payment webhook; deduplicate provider event IDs.
7. Create the customer only after verified payment.
8. Activate only after onboarding QA passes.

## Required negative tests
- Missing opt-in and do-not-contact both block outbound.
- Outbound is disabled by default.
- Unverified research cannot progress to contact.
- Cross-organization lead or webhook attempts are rejected.
- Invalid webhook signatures never mark a payment as received.
- Duplicate payment webhooks do not create a second customer.
- Failed payments do not create customers.
- Custom contracts and prices below the floor require human approval.
- Activation is blocked until payment is verified and onboarding QA passes.
- Invalid state transitions are rejected.

## Staging execution checklist
Run only against a dedicated staging project with test credentials and live actions disabled:

```bash
python scripts/check_rpc_contracts.py
python scripts/staging_smoke.py
python scripts/staging_tenant_isolation.py
pytest -q
python scripts/release_gate.py
```

The staging smoke and tenant-isolation scripts must be configured with staging-only credentials. Record the commit, migration versions, test timestamp, test organization IDs (non-sensitive aliases only), and sanitized results. Never paste keys, tokens, personal data, or payment details into the report.

## Acceptance criteria
- All local tests pass.
- Static release gate passes.
- Staging RPC contract checks pass against the installed schema.
- Two-organization tests prove cross-tenant reads and writes are denied.
- Provider sandbox tests prove signature verification, event deduplication, timeout reconciliation, and stable idempotency keys.
- A human can disable outbound actions and payments without redeploying.
- Audit logs record actor, organization, action, result, and correlation ID without secrets.

## Release decision
**NO-GO for live commercial automation until every staging criterion above has recorded evidence.** Passing local simulation tests alone is not sufficient. Start the first pilot with outbound and live payments disabled; enable them only after the owner signs off on staging evidence and rollback procedures.
