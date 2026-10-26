#!/usr/bin/env python3
"""Fail-closed verifier for human-collected operational staging rehearsal evidence.

Offline only: no network, database writes, or provider calls. It verifies the shape and
completeness of evidence references; it cannot independently prove that referenced tests ran.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

REQUIRED_CHECKS = (
    "tenant_isolation",
    "concurrent_claim_single_winner",
    "provider_idempotency_duplicate_suppressed",
    "unknown_outcome_reconciliation",
    "expired_lease_no_redispatch",
    "audit_trail_complete",
    "live_actions_disabled",
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


def _utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        return parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    except ValueError:
        return False


def evaluate_manifest(data: object) -> tuple[bool, list[str], dict[str, object]]:
    errors: list[str] = []
    normalized: dict[str, dict[str, object]] = {}
    if not isinstance(data, dict):
        return False, ["manifest root must be an object"], {"decision": "NO-GO"}
    if data.get("environment") != "staging":
        errors.append("environment must equal staging")
    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        errors.append("run_id must be a non-empty safe identifier (3-128 characters)")
    if not _utc_timestamp(data.get("started_at")):
        errors.append("started_at must be an ISO-8601 UTC timestamp ending in Z")
    checks = data.get("checks")
    if not isinstance(checks, list):
        errors.append("checks must be a list")
        checks = []
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            errors.append(f"checks[{index}] must be an object")
            continue
        name = item.get("check_name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"checks[{index}] has an empty check_name")
            continue
        name = name.strip()
        if name in normalized:
            errors.append(f"duplicate check: {name}")
            continue
        normalized[name] = item
        if item.get("result") != "PASS":
            errors.append(f"{name} result must be PASS")
        ref = item.get("evidence_ref")
        if not isinstance(ref, str) or not ref.strip() or ref.startswith(("/", "\\")) or ".." in Path(ref).parts:
            errors.append(f"{name} must include a relative evidence_ref without parent traversal")
        digest = item.get("evidence_sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            errors.append(f"{name} must include a 64-character SHA-256 evidence digest")
        if not _utc_timestamp(item.get("observed_at")):
            errors.append(f"{name} observed_at must be an ISO-8601 UTC timestamp ending in Z")
    for name in REQUIRED_CHECKS:
        if name not in normalized:
            errors.append(f"missing required check: {name}")
    report = {
        "schema_version": 1,
        "run_id": run_id if isinstance(run_id, str) else None,
        "environment": data.get("environment"),
        "decision": "GO_FOR_MANUAL_REVIEW" if not errors else "NO-GO",
        "required_checks": list(REQUIRED_CHECKS),
        "checks_received": len(normalized),
        "errors": errors,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "limitations": [
            "This tool validates manifest completeness and references, not the truth of attached evidence.",
            "A GO_FOR_MANUAL_REVIEW decision is not launch authorization; an operator must inspect artifacts.",
            "Provider, tenant-isolation, concurrency, and database behavior require actual staging execution.",
        ],
    }
    return not errors, errors, report


def verify_evidence_files(data: object, evidence_root: Path) -> list[str]:
    """Verify referenced artifacts exist under root and match their declared digest."""
    errors: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        return ["cannot verify artifacts without a manifest checks list"]
    try:
        root = evidence_root.resolve(strict=True)
    except OSError:
        return ["evidence root does not exist or cannot be resolved"]
    if not root.is_dir():
        return ["evidence root must be a directory"]
    for index, item in enumerate(data["checks"]):
        if not isinstance(item, dict):
            continue
        name = item.get("check_name", f"checks[{index}]")
        ref = item.get("evidence_ref")
        if not isinstance(ref, str) or not ref.strip():
            continue  # schema validation reports the missing reference
        relative = Path(ref)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            errors.append(f"{name} evidence_ref is not a safe relative path")
            continue
        candidate = root / relative
        # Reject symlinks in every component, including a symlinked final file.
        cursor = root
        symlink_found = False
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                symlink_found = True
                break
        if symlink_found:
            errors.append(f"{name} evidence path contains a symlink")
            continue
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file():
                errors.append(f"{name} evidence reference is not a regular file")
                continue
            content = resolved.read_bytes()
        except (OSError, ValueError):
            errors.append(f"{name} evidence file is missing or outside the evidence root")
            continue
        if not content.strip():
            errors.append(f"{name} evidence file is empty")
            continue
        actual = hashlib.sha256(content).hexdigest()
        declared = item.get("evidence_sha256")
        if not isinstance(declared, str) or actual.lower() != declared.lower():
            errors.append(f"{name} evidence SHA-256 does not match file content")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON evidence manifest collected during staging rehearsal")
    parser.add_argument("--report", type=Path, help="write machine-readable report JSON")
    parser.add_argument("--evidence-root", type=Path, required=True, help="directory containing the referenced evidence artifacts")
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"NO-GO: cannot read manifest ({type(exc).__name__})", file=sys.stderr)
        return 2
    ok, errors, report = evaluate_manifest(data)
    artifact_errors = verify_evidence_files(data, args.evidence_root)
    errors.extend(artifact_errors)
    report["artifact_verification"] = {"checked": True, "errors": artifact_errors}
    report["errors"] = errors
    if errors:
        report["decision"] = "NO-GO"
    else:
        report["decision"] = "GO_FOR_MANUAL_REVIEW"
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        try:
            args.report.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(f"NO-GO: cannot write report ({type(exc).__name__})", file=sys.stderr)
            return 2
    print(f"STAGING REHEARSAL: {report['decision']}")
    for error in errors:
        print(f"BLOCK {error}", file=sys.stderr)
    if not errors:
        print("Manifest is complete. Inspect every referenced artifact before any launch decision.")
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
