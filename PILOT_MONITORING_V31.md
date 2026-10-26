# v31 — Pilot monitoring and daily exception report

## Purpose
Produce a read-only daily summary for one organization from an exported JSONL event stream. The report intentionally contains aggregate operational metrics only; it drops names, emails, phone numbers, message bodies, and arbitrary event payloads.

## Input contract
Each line must be a JSON object with `organization_id`, `type`, and an offset-aware ISO-8601 `timestamp` (or `created_at`). Timestamps are normalized to UTC. Events without a valid timezone-aware timestamp are ignored and counted in the data-quality section. Events from other organizations are excluded before metrics are calculated.

## Run
```bash
python scripts/daily_pilot_report.py events.jsonl --organization-id agency-demo --date 2026-10-11
```
Exit code `1` indicates at least one critical provider-unknown-outcome alert; `2` indicates malformed input. This script reads a local export only. It does not connect to Supabase, send messages, write to a database, or verify a live deployment.

## Alert defaults
- `PROVIDER_OUTCOME_UNKNOWN`: critical when count is greater than 0; reconcile against the provider before retrying.
- `ACTION_FAILED`: high when count is greater than 0; inspect bounded error metadata and retry policy.
- `HUMAN_INTERVENTION_RATE_HIGH`: warning above 50%; review whether automation is failing or escalation policy is working as intended.

Thresholds can be adjusted explicitly via CLI flags. Alert levels are operational defaults, not guarantees or an SLA.

## Daily operator checklist
1. Export events through an approved, access-controlled method; do not put secrets in the export.
2. Generate one report per organization and store it in that organization's restricted workspace.
3. Resolve all critical unknown outcomes before replaying external actions.
4. Review failures, duplicates suppressed, and human-intervention rate.
5. Record action taken and owner for each unresolved exception in the existing incident process.
6. Keep live outbound and payments disabled until staging evidence and owner approval exist.

## Limitations
Local tests validate filtering, aggregation, redaction, thresholds, and CLI behavior. They do not prove event completeness, real tenant isolation in a database, delivery of alerts, or provider/Supabase behavior. A live staging export pipeline and operational alert destination remain future integration work.
