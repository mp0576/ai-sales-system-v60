#!/usr/bin/env python3
"""Exercise atomic replay claiming against a disposable Supabase staging fixture.

This probe never invokes an external provider. It races two claim RPCs for the same
approved replay request. A single winner is immediately finished as OUTCOME_UNKNOWN,
which sends the fixture to reconciliation (not back to the execution queue).
Requires explicit operator confirmation because it mutates the disposable fixture.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def evaluate_claim_results(results: list[dict | None]) -> dict:
    winners = sum(isinstance(item, dict) for item in results)
    return {
        "decision": "PASS" if winners == 1 and len(results) == 2 else "FAIL",
        "attempts": len(results),
        "winners": winners,
        "invariant": "exactly_one_worker_claims_the_same_approved_request",
    }


def run_probe(organization_id: str, replay_request_id: str, worker_prefix: str, lease_seconds: int) -> dict:
    # Import only after opt-in/config checks in main, so importing this module is safe.
    from app.repositories.supabase_exceptions import SupabaseOperationalExceptionStore
    from app.repositories.supabase_runtime import SupabaseRuntimeRepository

    store = SupabaseOperationalExceptionStore(SupabaseRuntimeRepository(timeout=15.0))
    barrier_workers = [f"{worker_prefix}-a", f"{worker_prefix}-b"]

    def claim(worker_id: str):
        try:
            result = store.claim_replay_dispatch(
                organization_id=organization_id,
                replay_request_id=replay_request_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            return {"worker": worker_id, "claimed": isinstance(result, dict), "claim": result}
        except Exception as exc:
            # Never expose exception strings: provider/DB responses can contain sensitive details.
            return {"worker": worker_id, "claimed": False, "error_code": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, worker) for worker in barrier_workers]
        outcomes = [future.result() for future in futures]

    raw_results = [item.get("claim") if item.get("claimed") else None for item in outcomes]
    evaluated = evaluate_claim_results(raw_results)
    finish_results = []
    winners = [item for item in outcomes if item.get("claimed")]
    # Even on a violated invariant, do not call an external provider. Attempt to move
    # any owned claim to reconciliation; SQL ownership checks reject non-owner finishes.
    for winner in winners:
        try:
            finished = store.finish_replay_dispatch(
                organization_id=organization_id,
                replay_request_id=replay_request_id,
                worker_id=winner["worker"],
                outcome="OUTCOME_UNKNOWN",
                result_code="STAGING_CONCURRENCY_PROBE",
            )
            finish_results.append({"worker": winner["worker"], "status": finished.get("status", "UNKNOWN")})
        except Exception as exc:
            finish_results.append({"worker": winner["worker"], "status": "RECONCILIATION_PENDING", "error_code": type(exc).__name__})

    return {
        "schema_version": 1,
        "probe": "staging_concurrent_replay_claim",
        "observed_at": utc_now(),
        "environment": "staging",
        "organization_id": organization_id,
        "replay_request_id": replay_request_id,
        "decision": evaluated["decision"] if all(not item.get("error_code") for item in outcomes) else "FAIL",
        "claim_invariant": evaluated,
        "workers": [{"worker": item["worker"], "claimed": item["claimed"], **({"error_code": item["error_code"]} if item.get("error_code") else {})} for item in outcomes],
        "cleanup": finish_results,
        "external_provider_called": False,
        "notes": ["Fixture must be disposable and approved before running.", "Winner is finished as OUTCOME_UNKNOWN; reconcile fixture manually if cleanup is pending."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="explicitly run mutating staging RPC probe")
    parser.add_argument("--confirm-disposable-fixture", action="store_true", help="confirm the request is disposable and may be moved to reconciliation")
    parser.add_argument("--output", type=Path, default=Path("staging-concurrency-probe.json"))
    parser.add_argument("--worker-prefix", default="staging-probe-v44")
    parser.add_argument("--lease-seconds", type=int, default=30)
    args = parser.parse_args()
    env = os.environ
    if not args.execute or not args.confirm_disposable_fixture:
        print("NO-GO: requires --execute and --confirm-disposable-fixture; no network request was made.", file=sys.stderr)
        return 2
    if env.get("APP_ENV", "").strip().lower() != "staging":
        print("NO-GO: APP_ENV must be explicitly set to staging.", file=sys.stderr)
        return 2
    if not env.get("SUPABASE_URL", "").startswith("https://"):
        print("NO-GO: SUPABASE_URL must be an HTTPS staging project URL.", file=sys.stderr)
        return 2
    if not env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip():
        print("NO-GO: trusted backend service-role credential is required; value is never printed.", file=sys.stderr)
        return 2
    org_id = env.get("STAGING_PROBE_ORGANIZATION_ID", "").strip()
    replay_id = env.get("STAGING_PROBE_REPLAY_REQUEST_ID", "").strip()
    if not UUID_RE.fullmatch(org_id) or not UUID_RE.fullmatch(replay_id):
        print("NO-GO: provide valid UUID fixture IDs in STAGING_PROBE_ORGANIZATION_ID and STAGING_PROBE_REPLAY_REQUEST_ID.", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,60}", args.worker_prefix) or not 15 <= args.lease_seconds <= 300:
        print("NO-GO: invalid worker prefix or lease duration.", file=sys.stderr)
        return 2
    try:
        report = run_probe(org_id, replay_id, args.worker_prefix, args.lease_seconds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"NO-GO: probe failed ({type(exc).__name__}); no sensitive details displayed.", file=sys.stderr)
        return 1
    print(json.dumps({"decision": report["decision"], "output": str(args.output), "external_provider_called": False}, indent=2))
    return 0 if report["decision"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
