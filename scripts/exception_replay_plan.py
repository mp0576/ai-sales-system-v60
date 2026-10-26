#!/usr/bin/env python3
"""Read-only exception replay planner. Reads a JSON array and never dispatches work."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pilot.replay_policy import plan_exception_replay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file containing an array of exception/action records")
    parser.add_argument("--max-replays", type=int, default=3, help="bounded replay budget (1..10)")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ValueError("input must be a JSON array of objects")
        result = [{"exception_id": row.get("exception_id"), **plan_exception_replay(row, max_replays=args.max_replays)} for row in data]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"mode": "READ_ONLY_PLAN", "items": result,
                      "note": "No database writes, queue mutations, or provider calls were performed."}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
