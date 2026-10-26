#!/usr/bin/env python3
"""Fail-closed evaluator for the CSV exported from staging_replay_dispatch_acceptance.sql.

The SQL itself is read-only. This evaluator performs no network calls and never mutates staging.
Expected CSV columns: check_name,result,detail. Every result must be PASS and every required
check must appear. A passing report is catalog/grant evidence, not proof of concurrency behavior.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path
import sys

REQUIRED_PREFIXES = (
    "rpc_exists:", "service_role_execute:", "client_execute_revoked:",
    "rls_enabled:", "dispatch_columns:",
)
REQUIRED_EXACT = {
    "atomic_claim_locking", "expired_lease_reconciliation_only",
    "claim_rpc_security_definer_search_path",
}


def evaluate_rows(rows: list[dict[str, str]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    normalized: dict[str, str] = {}
    for row in rows:
        name = (row.get("check_name") or "").strip()
        result = (row.get("result") or "").strip().upper()
        if not name:
            errors.append("row with empty check_name")
            continue
        if name in normalized:
            errors.append(f"duplicate check: {name}")
            continue
        normalized[name] = result
        if result != "PASS":
            errors.append(f"{name} returned {result or 'EMPTY'}")
    for prefix in REQUIRED_PREFIXES:
        found = [name for name in normalized if name.startswith(prefix)]
        if not found:
            errors.append(f"missing required check group: {prefix}")
        elif any(normalized[name] != "PASS" for name in found):
            pass  # The row-level failure above provides the precise reason.
    for name in sorted(REQUIRED_EXACT):
        if name not in normalized:
            errors.append(f"missing required check: {name}")
    # The SQL query is expected to return five function checks for each privilege family,
    # three RLS checks and six dispatch-column checks. Minimum counts prevent partial exports.
    minimums = {"rpc_exists:": 5, "service_role_execute:": 5,
                "client_execute_revoked:": 5, "rls_enabled:": 3, "dispatch_columns:": 6}
    for prefix, minimum in minimums.items():
        count = sum(name.startswith(prefix) for name in normalized)
        if count < minimum:
            errors.append(f"incomplete {prefix} group: {count}/{minimum} rows")
    return not errors, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path, help="CSV exported from the read-only SQL acceptance query")
    args = parser.parse_args()
    try:
        with args.csv_file.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"check_name", "result", "detail"}
            if not required.issubset(set(reader.fieldnames or [])):
                print("BLOCK: CSV must contain check_name,result,detail", file=sys.stderr)
                return 2
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        print(f"BLOCK: cannot read acceptance CSV ({type(exc).__name__})", file=sys.stderr)
        return 2
    ok, errors = evaluate_rows(rows)
    for row in rows:
        name = (row.get("check_name") or "").strip()
        result = (row.get("result") or "").strip().upper()
        print(f"{'PASS' if result == 'PASS' else 'BLOCK'} {name}: {result or 'EMPTY'}")
    if not ok:
        for error in errors:
            print(f"BLOCK {error}", file=sys.stderr)
        print("STAGING CATALOG ACCEPTANCE: NO-GO", file=sys.stderr)
        return 1
    print("STAGING CATALOG ACCEPTANCE: PASS. Concurrency, tenant behavior, and provider idempotency still require the operational rehearsal.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
