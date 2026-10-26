#!/usr/bin/env python3
"""Validate a tenant-scoped lead CSV without importing or contacting anyone."""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pilot.lead_import import validate_csv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--organization-id", required=True)
    args = parser.parse_args()
    report = validate_csv(args.csv_file.read_text(encoding="utf-8-sig"), args.organization_id)
    output = {
        "accepted_count": report.valid_count,
        "rejected": report.rejected,
        "duplicates": report.duplicates,
        "non_contactable_ids": report.non_contactable,
        "side_effects": "none; validation only",
    }
    print(json.dumps(output, indent=2))
    return 1 if report.rejected or report.duplicates else 0

if __name__ == "__main__":
    raise SystemExit(main())
