#!/usr/bin/env python3
"""Generate a tenant-scoped daily report from an exported JSONL event file (read-only)."""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pilot.monitoring import build_daily_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events_jsonl", type=Path, help="one JSON event object per line")
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--date", dest="report_date", help="UTC date YYYY-MM-DD; defaults to today")
    parser.add_argument("--max-unknown-outcomes", type=int, default=0)
    parser.add_argument("--max-failed-actions", type=int, default=0)
    parser.add_argument("--max-human-intervention-rate", type=float, default=0.5)
    args = parser.parse_args()
    report_date = args.report_date or datetime.now(timezone.utc).date().isoformat()
    events = []
    for line_number, line in enumerate(args.events_jsonl.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            print(f"Invalid JSON on line {line_number}; refusing to generate a partial report.", file=sys.stderr)
            return 2
        if not isinstance(item, dict):
            print(f"Line {line_number} must contain a JSON object.", file=sys.stderr)
            return 2
        events.append(item)
    try:
        report = build_daily_report(events, args.organization_id, report_date,
            max_unknown_outcomes=args.max_unknown_outcomes,
            max_failed_actions=args.max_failed_actions,
            max_human_intervention_rate=args.max_human_intervention_rate)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if any(alert["severity"] == "critical" for alert in report["alerts"]) else 0

if __name__ == "__main__":
    raise SystemExit(main())
