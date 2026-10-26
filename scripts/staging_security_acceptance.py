#!/usr/bin/env python3
"""Combine real staging tenant-isolation and replay-concurrency evidence.

This command does not execute SQL or provider actions. Tenant isolation is read-only;
the concurrency report must have been produced separately by the opt-in v44 probe.
A PASS means the supplied evidence meets these checks, not that the application is
certified secure.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import re
from pathlib import Path
import sys

from scripts.staging_tenant_isolation import run_checks


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_concurrency_report(report: object, *, now: datetime | None = None) -> tuple[bool, str]:
    """Validate structural, identity, cleanup and freshness properties of probe evidence."""
    if not isinstance(report, dict):
        return False, "report_not_object"
    if report.get("schema_version") != 1 or report.get("probe") != "staging_concurrent_replay_claim":
        return False, "unexpected_report_schema"
    if report.get("environment") != "staging":
        return False, "environment_not_staging"
    if report.get("decision") != "PASS" or report.get("external_provider_called") is not False:
        return False, "probe_not_passed_or_provider_flag_invalid"
    try:
        observed = datetime.fromisoformat(str(report.get("observed_at", "")).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return False, "timestamp_missing_timezone"
        current = now or datetime.now(timezone.utc)
        age = current - observed.astimezone(timezone.utc)
        if age < timedelta(minutes=-5) or age > timedelta(hours=24):
            return False, "evidence_timestamp_out_of_window"
    except (ValueError, TypeError):
        return False, "evidence_timestamp_invalid"
    uuid_re = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
    if not uuid_re.fullmatch(str(report.get("organization_id", ""))) or not uuid_re.fullmatch(str(report.get("replay_request_id", ""))):
        return False, "fixture_identity_invalid"
    invariant = report.get("claim_invariant")
    if not isinstance(invariant, dict) or invariant.get("decision") != "PASS" or invariant.get("winners") != 1 or invariant.get("attempts") != 2:
        return False, "claim_invariant_failed"
    workers = report.get("workers")
    if not isinstance(workers, list) or len(workers) != 2 or sum(isinstance(w, dict) and w.get("claimed") is True for w in workers) != 1:
        return False, "worker_results_invalid"
    worker_ids = [w.get("worker") for w in workers if isinstance(w, dict)]
    if len(worker_ids) != 2 or any(not isinstance(w, str) or not w for w in worker_ids) or len(set(worker_ids)) != 2:
        return False, "worker_identity_invalid"
    if any(not isinstance(w, dict) or w.get("error_code") for w in workers):
        return False, "worker_error_present"
    cleanup = report.get("cleanup")
    winner_ids = {w.get("worker") for w in workers if isinstance(w, dict) and w.get("claimed") is True}
    if not isinstance(cleanup, list) or {x.get("worker") for x in cleanup if isinstance(x, dict)} != winner_ids:
        return False, "cleanup_evidence_missing"
    allowed_statuses = {"RECONCILIATION_REQUIRED", "OUTCOME_UNKNOWN", "RECONCILIATION_PENDING"}
    if any(not isinstance(item, dict) or item.get("error_code") or item.get("status") not in allowed_statuses for item in cleanup):
        return False, "cleanup_incomplete"
    return True, "concurrency_report_validated"


def build_report(env: dict[str, str], concurrency_path: Path | None) -> dict:
    checks = run_checks(env)
    tenant_checks = [
        {"name": c.name, "decision": "PASS" if c.ok else "FAIL", "detail": c.detail}
        for c in checks
    ]
    tenant_ok = bool(checks) and all(c.ok for c in checks)
    concurrency: dict = {"decision": "BLOCKED", "reason": "concurrency_report_not_supplied"}
    if concurrency_path is not None:
        try:
            raw = concurrency_path.read_bytes()
            parsed = json.loads(raw.decode("utf-8"))
            ok, reason = validate_concurrency_report(parsed)
            concurrency = {
                "decision": "PASS" if ok else "FAIL",
                "reason": reason,
                "evidence_file": concurrency_path.name,
                "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            concurrency = {"decision": "FAIL", "reason": "concurrency_report_unreadable", "evidence_file": concurrency_path.name}
    all_ok = tenant_ok and concurrency.get("decision") == "PASS"
    return {
        "schema_version": 1,
        "report": "staging_security_acceptance",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": "staging" if env.get("APP_ENV", "").strip().lower() == "staging" else "unconfirmed",
        "decision": "PASS" if all_ok else "NO_GO",
        "tenant_isolation": {"decision": "PASS" if tenant_ok else "FAIL", "checks": tenant_checks},
        "concurrency": concurrency,
        "external_provider_called_by_this_command": False,
        "limitations": [
            "Tenant-isolation requests are read-only and use the supplied user JWTs.",
            "Concurrency evidence is validated from a separately produced report and is not re-executed here.",
            "A PASS is not a security certification and does not validate provider idempotency or production readiness.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency-report", type=Path, help="JSON output from staging_concurrent_replay_claim.py")
    parser.add_argument("--output", type=Path, default=Path("staging-security-acceptance.json"))
    args = parser.parse_args()
    env = dict(os.environ)
    if env.get("APP_ENV", "").strip().lower() != "staging":
        print("NO-GO: APP_ENV must be explicitly set to staging; no network request was made.", file=sys.stderr)
        return 2
    report = build_report(env, args.concurrency_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": report["decision"], "output": str(args.output), "tenant_isolation": report["tenant_isolation"]["decision"], "concurrency": report["concurrency"]["decision"]}, indent=2))
    return 0 if report["decision"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
