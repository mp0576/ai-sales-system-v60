#!/usr/bin/env python3
"""Verify operator-collected v53 staging acceptance evidence; never performs network calls.

Evidence JSON schema is documented in STAGING_ACCEPTANCE_V53.md. The verifier is
fail-closed: missing, stale, mismatched, or failed checks block acceptance.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

REQUIRED_CHECKS = {
    "auth_user_a", "auth_user_b", "tenant_isolation_a_to_b",
    "tenant_isolation_b_to_a", "same_key_replay", "concurrent_first_write",
    "stale_version_conflict", "migration_0024_applied", "live_actions_disabled",
}
MAX_AGE_HOURS = 24


def validate_evidence(data: object, *, now: datetime | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["evidence root must be a JSON object"]
    if data.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    project_ref = data.get("project_ref")
    if not isinstance(project_ref, str) or not re.fullmatch(r"[a-z0-9]{20}", project_ref):
        errors.append("project_ref must be the non-secret 20-character Supabase project ref")
    stamp = data.get("captured_at")
    try:
        captured = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError("timezone required")
        current = now or datetime.now(timezone.utc)
        age_hours = (current - captured.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours < -0.05:
            errors.append("captured_at is in the future")
        elif age_hours > MAX_AGE_HOURS:
            errors.append(f"evidence is stale (older than {MAX_AGE_HOURS} hours)")
    except (AttributeError, TypeError, ValueError):
        errors.append("captured_at must be an ISO-8601 timestamp with timezone")
    org_a, org_b = data.get("organization_a"), data.get("organization_b")
    if not isinstance(org_a, str) or not org_a.strip() or not isinstance(org_b, str) or not org_b.strip():
        errors.append("organization_a and organization_b are required")
    elif org_a == org_b:
        errors.append("test users must belong to different organizations")
    checks = data.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be an object")
    else:
        missing = sorted(REQUIRED_CHECKS - checks.keys())
        if missing:
            errors.append("missing required checks: " + ", ".join(missing))
        failed = sorted(name for name, result in checks.items() if result is not True)
        if failed:
            errors.append("checks must all be literal true; failed/invalid: " + ", ".join(failed))
    if data.get("live_outbound_enabled") is not False:
        errors.append("live_outbound_enabled must be false")
    if data.get("live_payments_enabled") is not False:
        errors.append("live_payments_enabled must be false")
    if not isinstance(data.get("operator"), str) or not data["operator"].strip():
        errors.append("operator label is required")
    # Reject likely credential fields rather than accidentally persisting secrets in evidence.
    forbidden = {"service_role_key", "anon_key", "access_token", "refresh_token", "jwt", "password", "secret"}
    def scan(value, trail="evidence"):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in forbidden:
                    errors.append(f"forbidden credential field: {trail}.{key}")
                scan(child, f"{trail}.{key}")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                scan(child, f"{trail}[{i}]")
    scan(data)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="operator-collected staging evidence JSON")
    parser.add_argument("--report", type=Path, help="optional path to write a sanitized Markdown report")
    args = parser.parse_args()
    try:
        data = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"BLOCK: cannot read valid evidence JSON: {exc}", file=sys.stderr)
        return 2
    errors = validate_evidence(data)
    status = "BLOCKED" if errors else "ACCEPTED"
    lines = [
        "# v53 Staging Acceptance Verification", "",
        f"- Result: **{status}**",
        f"- Project ref: `{data.get('project_ref', 'unknown')}`" if isinstance(data, dict) else "- Project ref: unknown",
        f"- Captured at: `{data.get('captured_at', 'unknown')}`" if isinstance(data, dict) else "- Captured at: unknown",
        "- Live outbound: disabled",
        "- Live payments: disabled", "",
    ]
    if errors:
        lines += ["## Blocking issues", *[f"- {error}" for error in errors], ""]
    else:
        lines += ["All required staging acceptance checks passed. This evidence is time-bounded and does not certify provider messaging, calendar, or payment integrations.", ""]
    report = "\n".join(lines)
    print(report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
