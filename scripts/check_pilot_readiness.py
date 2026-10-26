#!/usr/bin/env python3
"""Fail-closed static check for pilot readiness report completeness; no network or writes."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "PILOT_READINESS_REPORT.md"
REQUIRED = (
    "Release decision: BLOCKED for live customer traffic",
    "Mandatory blockers before pilot",
    "two organizations",
    "cross-tenant reads and writes are denied",
    "provider sandbox",
    "OUTBOUND_ENABLED=false",
    "ENABLE_LIVE_PAYMENTS=false",
    "NO-GO for live commercial automation",
)

def check_report(root: Path = ROOT) -> tuple[bool, list[str]]:
    path = root / "PILOT_READINESS_REPORT.md"
    if not path.is_file():
        return False, ["pilot_readiness_report_missing"]
    content = path.read_text(encoding="utf-8")
    missing = [item for item in REQUIRED if item.lower() not in content.lower()]
    return not missing, missing

def main() -> int:
    ok, missing = check_report()
    if ok:
        print("PASS pilot_readiness_report: blockers, safe defaults, evidence limits and NO-GO decision documented")
        return 0
    print("BLOCK pilot_readiness_report: missing " + ", ".join(missing), file=sys.stderr)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
