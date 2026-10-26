# MVP v48 — Real-estate lead journey simulation

## Purpose

This increment shifts the project toward a demonstrable real-estate commercial workflow. It adds a deterministic, offline simulation that scores leads, applies contact-permission guardrails, proposes simulated next actions, and routes sensitive cases to human review.

## Run

```bash
python scripts/simulate_real_estate_golden_path.py
python scripts/simulate_real_estate_golden_path.py --input examples/real_estate_leads_v48.json --output /tmp/real-estate-report.json
```

Input is JSON with an `organization_id` and a `leads` array. Each lead may contain only the fields represented by `RealEstateLead`; unknown fields are rejected. The example fixture includes a qualified buyer, a no-consent lead, and a lead requesting a discount above the automatic limit.

## Behavior

- Tenant mismatch and disabled automation fail closed.
- Missing contact consent and do-not-contact suppress outbound contact actions.
- Scoring is deterministic and rule-based; it is a prototype, not a validated predictive model.
- A requested discount above 10%, custom contract, legal question, serious complaint, or strategic-client flag creates a human-approval action.
- Visit availability is supplied by the fixture and is never queried from a live calendar.
- All actions are marked simulated and `external_side_effect: false`. The simulator makes no network calls and cannot send messages, book calendars, change CRM records, or take payments.
- Stable action idempotency keys suppress repeated actions when the same lead is processed again in the same in-memory instance. This is not a substitute for the durable production idempotency store.
- Audit event IDs are content-derived for reproducibility; they are not a trusted timestamp or proof of external execution.

## Acceptance and limits

Run `pytest -q`, `python -m compileall -q app scripts`, `python scripts/check_rpc_contracts.py`, and `python scripts/release_gate.py --static-only`.

Passing local tests only establishes the local simulation contract. It does not certify remote Supabase/Postgres, RLS, deployed RPC grants, WhatsApp, email, CRM, calendar, payment providers, legal compliance, or production readiness. Keep live outbound and payments disabled until a separate staging rehearsal and human review have passed.
