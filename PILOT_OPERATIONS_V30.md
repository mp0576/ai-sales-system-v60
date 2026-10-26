# MVP v30 — Controlled Pilot Operations Pack

## Purpose
Prepare one real-estate agency for a controlled pilot with observable metrics and safe lead intake. This pack does not enable outbound messages or persist imported leads.

## Lead import
1. Export only leads the agency is entitled to process.
2. Keep one CSV per organization and set `organization_id` to the exact tenant ID.
3. Preserve the consent evidence and timestamp; never infer consent from a phone number or email address.
4. Run the validator before any import:

```bash
python scripts/validate_pilot_leads.py templates/pilot_leads_template.csv --organization-id agency-demo
```

5. Review rejected rows and duplicates. `opt_out` and `unknown` rows may be staged for recordkeeping but are marked non-contactable. An `opt_in` row must include a valid ISO timestamp.
6. Validation is read-only: it does not write to a database, call a provider, or send a message. A separate approved import implementation and legal basis review are required before persistence or contact.

## Pilot KPIs
The `app.pilot.metrics.calculate_pilot_metrics` helper reports funnel counts, response/qualification/booking rates, human intervention, unknown provider outcomes, failed actions and duplicate suppression. Supply deduplicated, tenant-scoped audit events; do not combine data from different organizations.

## Pilot guardrails
- Start with one agency, a small manually reviewed cohort, and outbound disabled.
- Verify consent, suppression/DNC status, source and tenant ownership before enabling contact.
- Keep payments disabled; use sandbox only after provider credentials and webhook verification are configured.
- Route legal questions, custom contracts, large refunds, complaints and uncertain provider outcomes to a human.
- Define an owner, support contact, rollback path and daily review of failures before any live pilot.
- Track response time, visit bookings, qualification, opt-outs/complaints, duplicate suppression, human intervention and provider cost.

## Exit criteria
- No cross-tenant data observed in tests.
- Consent and opt-out enforcement verified end-to-end.
- Provider timeout-after-acceptance recovery tested in sandbox.
- Audit records and alerts reviewed by the agency owner.
- Metrics reviewed against an agreed baseline and written success threshold.

Local tests and CSV validation are not proof of deployed RLS, legal compliance, or provider behavior. Live launch remains blocked until staging evidence is recorded.
