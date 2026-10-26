#!/usr/bin/env python3
"""Build a read-only tenant-scoped exception queue from JSONL exported events."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pilot.exceptions import build_exception_queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events_jsonl", type=Path)
    parser.add_argument("--organization-id", required=True)
    args = parser.parse_args()
    events = []
    for number, line in enumerate(args.events_jsonl.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            print(f"Invalid JSON on line {number}; refusing partial queue.", file=sys.stderr)
            return 2
        if not isinstance(value, dict):
            print(f"Line {number} must contain a JSON object.", file=sys.stderr)
            return 2
        events.append(value)
    try:
        queue = build_exception_queue(events, args.organization_id)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(queue, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
