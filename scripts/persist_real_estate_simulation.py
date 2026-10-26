#!/usr/bin/env python3
"""Run the offline real-estate simulation and persist snapshots locally for rehearsal.

No network, provider, calendar, CRM, messaging or payment calls are performed.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.repositories.real_estate_leads import SQLiteLeadRepository
from app.simulation.real_estate import RealEstateJourney, lead_from_dict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "examples" / "real_estate_leads_v48.json")
    parser.add_argument("--db", type=Path, required=True, help="Local SQLite file for this rehearsal")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("organization_id"), str) or not isinstance(payload.get("leads"), list):
            raise ValueError("Input must contain organization_id and a leads array")
        org = payload["organization_id"]
        journey = RealEstateJourney(org)
        repo = SQLiteLeadRepository(args.db)
        results = []
        for item in payload["leads"]:
            lead = lead_from_dict({"organization_id": org, **item})
            result = journey.process(lead)
            saved = repo.save_snapshot(organization_id=org, lead_id=lead.lead_id,
                state=result["state"], payload={"score": result["score"], "actions": result["actions"],
                    "simulation_only": True, "external_side_effects": 0},
                event_type="SIMULATED_LEAD_PROCESSED", idempotency_key=f"simulation-v49:{lead.lead_id}")
            results.append({"lead_id": lead.lead_id, "state": result["state"], "score": result["score"],
                            "persisted_version": saved["version"], "duplicate_persistence": saved["duplicate"]})
        report = {"version": 49, "mode": "local_persistence_rehearsal", "external_side_effects": 0,
                  "organization_id": org, "database_path": str(args.db), "leads_processed": len(results),
                  "results": results}
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (OSError, json.JSONDecodeError, TypeError, ValueError, PermissionError) as exc:
        print(f"PERSISTENCE_REHEARSAL_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
