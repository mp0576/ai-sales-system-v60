# Operations runbook

## Health and startup
- `GET /health` reports process-level health only; it does not verify Supabase, n8n or provider connectivity.
- Run `python scripts/preflight.py` before starting the pilot service.
- Run `python -m pytest -q` before packaging a release.
- Compose logs: `docker compose logs --tail=200 api`; status: `docker compose ps`.

## Daily checks
- Review pending human approvals and unresolved incidents.
- Check provider error rates, retry backlog and dead-letter queue once connected to durable infrastructure.
- Check AI spend against tenant limits and investigate cost spikes.
- Check automation success and human-intervention rates against measured baselines, not demo metrics.
- Confirm DNC/consent suppressions and webhook processing delays.

## Incident response
1. Disable outbound/automation using the application and provider-side kill switches.
2. Preserve relevant logs, request/correlation IDs, provider event IDs and approval decisions.
3. Determine affected tenants and whether any external message, appointment or payment occurred.
4. Reconcile provider state before replaying failed events; never blindly replay payment events.
5. Rotate potentially exposed credentials and restrict access.
6. Restore from known-good image/configuration; validate tenant isolation and Golden Path before resuming.
7. Record root cause, impact, remediation and follow-up tests.

## Human approval standards
- A pending approval must include a tenant, action, reason, risk and expiry policy in the production implementation.
- Approve only within delegated authority. Reject or escalate legal questions, custom contracts, strategic accounts, high refunds and exceptions outside the price floor.
- Approval decisions must be durable and auditable; UI state alone is not evidence of execution.

## Data and backup
- The current dashboard demo store is not persistent and has no business-data backup requirement because it is synthetic.
- Before production, define database backups, point-in-time recovery, retention, deletion/export handling, restore frequency and recovery objectives. Test restoration, not just backup creation.
