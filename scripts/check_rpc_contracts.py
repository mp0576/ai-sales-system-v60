#!/usr/bin/env python3
"""Static contract check between Python RPC callers and SQL migration signatures.

This does not connect to PostgreSQL and does not prove deployed functions/grants.
Use sql/staging_contract_check.sql against a dedicated staging database for that.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "sql" / "migrations"

# Function name -> expected argument names in call order. Kept explicit so drift is visible.
EXPECTED = {
    "save_operational_lead_snapshot": ["p_organization_id", "p_lead_id", "p_state", "p_payload", "p_event_type", "p_idempotency_key", "p_expected_version"],
    "claim_action_idempotency": ["p_organization_id", "p_action_type", "p_idempotency_key", "p_worker_id", "p_lease_seconds"],
    "finish_action_idempotency": ["p_organization_id", "p_action_type", "p_idempotency_key", "p_worker_id", "p_result", "p_retryable"],
    "claim_provider_webhook": ["p_organization_id", "p_provider", "p_event_id", "p_worker_id", "p_lease_seconds", "p_provider_created_at", "p_object_id"],
    "finish_provider_webhook": ["p_organization_id", "p_provider", "p_event_id", "p_worker_id", "p_succeeded", "p_error_code"],
    "create_lead_with_event": ["p_organization_id", "p_state", "p_contact_id", "p_facts", "p_metadata", "p_idempotency_key"],
    "append_event_to_outbox": ["p_organization_id", "p_event_type", "p_payload", "p_lead_id", "p_idempotency_key", "p_topic"],
    "claim_outbox": ["batch_size", "worker_id", "lease_seconds"],
    "finish_outbox": ["p_organization_id", "p_outbox_id", "p_worker_id", "p_succeeded", "p_error", "p_retry_delay_seconds", "p_permanent"],
    "create_operational_exception": ["p_organization_id", "p_source_type", "p_source_id", "p_code", "p_severity", "p_summary"],
    "transition_operational_exception": ["p_organization_id", "p_exception_id", "p_actor_user_id", "p_action", "p_assigned_to", "p_note"],
    "request_exception_replay": ["p_organization_id", "p_exception_id", "p_actor_user_id", "p_replay_number", "p_failure_class", "p_external_outcome", "p_idempotency_key", "p_reason"],
    "decide_exception_replay": ["p_organization_id", "p_replay_request_id", "p_actor_user_id", "p_approve", "p_note"],
    "claim_exception_replay": ["p_organization_id", "p_replay_request_id", "p_worker_id", "p_lease_seconds"],
    "finish_exception_replay": ["p_organization_id", "p_replay_request_id", "p_worker_id", "p_outcome", "p_result_code"],
    "reconcile_expired_exception_replays": ["p_cutoff"],
}


def normalize_args(raw: str) -> list[str]:
    # SQL argument definitions are simple `name type` pairs in this project's migrations.
    return [part.strip().split()[0].lower() for part in raw.split(",") if part.strip()]


def find_function(sql: str, name: str) -> list[str] | None:
    pattern = re.compile(r"create\s+or\s+replace\s+function\s+public\." + re.escape(name) + r"\s*\((.*?)\)\s*returns", re.I | re.S)
    matches = list(pattern.finditer(sql))
    # Later migrations may replace a function with a new signature; the last definition wins.
    match = matches[-1] if matches else None
    return normalize_args(match.group(1)) if match else None


def check_contracts(root: Path = ROOT) -> list[tuple[str, bool, str]]:
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted((root / "sql" / "migrations").glob("*.sql")))
    checks = []
    for name, expected in EXPECTED.items():
        actual = find_function(sql, name)
        ok = actual == expected
        checks.append((f"rpc_signature_{name}", ok,
                       "signature matches Python contract" if ok else f"expected {expected}; found {actual}"))
    # Every privileged RPC used by workers must be service-role only.
    lower = sql.lower()
    for name in ("claim_action_idempotency", "finish_action_idempotency", "claim_provider_webhook", "finish_provider_webhook", "claim_outbox", "finish_outbox", "create_operational_exception", "transition_operational_exception", "request_exception_replay", "decide_exception_replay", "claim_exception_replay", "finish_exception_replay", "reconcile_expired_exception_replays"):
        grant = re.search(r"grant\s+execute\s+on\s+function\s+public\." + re.escape(name) + r"\s*\([^;]*?\)\s+to\s+service_role\s*;", lower, re.S)
        revoke = re.search(r"revoke\s+all\s+on\s+function\s+public\." + re.escape(name) + r"\s*\([^;]*?\)\s+from\s+public\s*,\s*anon\s*,\s*authenticated\s*;", lower, re.S)
        checks.append((f"rpc_privilege_{name}", bool(grant and revoke),
                       "service_role grant and client-role revocation found" if grant and revoke else "missing service_role grant or client-role revocation"))
    return checks


def main() -> int:
    checks = check_contracts()
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    failures = sum(not ok for _, ok, _ in checks)
    print(f"RPC contract checks: {len(checks) - failures}/{len(checks)} passed")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
