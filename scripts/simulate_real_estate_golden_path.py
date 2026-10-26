#!/usr/bin/env python3
"""Run an offline real-estate lead journey simulation. No network/provider calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.simulation.real_estate import RealEstateJourney, lead_from_dict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "examples" / "real_estate_leads_v48.json")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path (default: stdout)")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("organization_id"), str) or not isinstance(payload.get("leads"), list):
            raise ValueError("Input must contain organization_id and a leads array")
        journey = RealEstateJourney(payload["organization_id"])
        results = [journey.process(lead_from_dict({"organization_id": payload["organization_id"], **item})) for item in payload["leads"]]
        report = {"version": 48, "mode": "simulation_only", "external_side_effects": 0,
                  "summary": {"leads": len(results), "states": {state: sum(r["state"] == state for r in results) for state in sorted({r["state"] for r in results})},
                              "actions": sum(len(r["actions"]) for r in results),
                              "pending_approvals": sum(r["state"] == "HUMAN_APPROVAL_REQUIRED" for r in results)},
                  "results": results}
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (OSError, json.JSONDecodeError, TypeError, ValueError, PermissionError) as exc:
        print(f"SIMULATION_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
