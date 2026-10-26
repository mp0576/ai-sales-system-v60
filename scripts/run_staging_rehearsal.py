#!/usr/bin/env python3
"""Run available read-only staging probes and emit hashed evidence + fail-closed manifest.

This runner never applies migrations or calls business providers. The only network
probes delegated to child scripts are GET-only Supabase health/table/RLS checks.
Unimplemented operational checks are explicitly marked FAIL, never assumed PASS.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
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
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_rehearsal(root: Path, output_dir: Path, env: dict[str, str], run_id: str) -> tuple[dict[str, object], int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = output_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    started_at = _utc()
    results: dict[str, tuple[str, str]] = {}

    def record(name: str, result: str, evidence: str, detail: str) -> None:
        path = artifacts / evidence
        path.write_text(detail.rstrip() + "\n", encoding="utf-8")
        results[name] = (result, evidence)

    app_env = env.get("APP_ENV", "staging").strip().lower()
    if app_env != "staging":
        for name in REQUIRED_CHECKS:
            record(name, "FAIL", f"{name}.log", f"BLOCKED: APP_ENV must be staging, received {app_env or '<empty>'}")
    else:
        probes = (
            ("tenant_isolation", "staging_tenant_isolation.py"),
            ("_smoke", "staging_smoke.py"),
        )
        probe_pass: dict[str, bool] = {}
        for key, script in probes:
            command = [sys.executable, str(root / "scripts" / script)]
            try:
                completed = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                           text=True, timeout=90, check=False)
                detail = f"command={script}\nexit_code={completed.returncode}\n--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
                ok = completed.returncode == 0
            except subprocess.TimeoutExpired as exc:
                detail = f"command={script}\nTIMEOUT after {exc.timeout} seconds\nNo PASS can be inferred."
                ok = False
            except OSError as exc:
                detail = f"command={script}\nEXECUTION_ERROR={type(exc).__name__}\nNo PASS can be inferred."
                ok = False
            probe_pass[key] = ok
            if key == "tenant_isolation":
                record("tenant_isolation", "PASS" if ok else "FAIL", "tenant_isolation.log", detail)
            else:
                record("_smoke", "PASS" if ok else "FAIL", "supabase_readonly_smoke.log", detail)

        # No automated concurrency/provider test is present in this pack; explicitly block it.
        missing = {
            "concurrent_claim_single_winner": "No live concurrent-claim staging probe is implemented in this runner.",
            "provider_idempotency_duplicate_suppressed": "No provider sandbox credentials or duplicate-suppression probe supplied.",
            "unknown_outcome_reconciliation": "No live ambiguous-outcome reconciliation probe is implemented in this runner.",
            "expired_lease_no_redispatch": "No live expired-lease redispatch probe is implemented in this runner.",
            "audit_trail_complete": "No live audit-trail assertion is implemented in this runner.",
        }
        for name, reason in missing.items():
            record(name, "FAIL", f"{name}.log", "BLOCKED: " + reason)

        outbound = env.get("OUTBOUND_ENABLED", "false").strip().lower()
        payments = env.get("ENABLE_LIVE_PAYMENTS", "false").strip().lower()
        disabled = outbound in {"", "0", "false", "no", "off"} and payments in {"", "0", "false", "no", "off"}
        record("live_actions_disabled", "PASS" if disabled else "FAIL", "live_actions_disabled.log",
               f"APP_ENV={app_env}\nOUTBOUND_ENABLED={'<unset>' if 'OUTBOUND_ENABLED' not in env else outbound}\nENABLE_LIVE_PAYMENTS={'<unset>' if 'ENABLE_LIVE_PAYMENTS' not in env else payments}\nBoth outbound and live payments must be disabled.")

    checks = []
    for name in REQUIRED_CHECKS:
        result, evidence = results[name]
        path = artifacts / evidence
        checks.append({"check_name": name, "result": result,
                       "evidence_ref": f"artifacts/{evidence}", "evidence_sha256": _sha(path), "observed_at": _utc()})
    manifest = {"environment": "staging", "run_id": run_id, "started_at": started_at,
                "runner": "scripts/run_staging_rehearsal.py", "checks": checks}
    manifest_path = output_dir / "rehearsal-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {"run_id": run_id, "decision": "NO-GO" if any(c["result"] != "PASS" for c in checks) else "GO_FOR_MANUAL_REVIEW",
              "passed": sum(c["result"] == "PASS" for c in checks), "blocked_or_failed": sum(c["result"] != "PASS" for c in checks),
              "manifest": str(manifest_path), "artifacts_dir": str(artifacts),
              "note": "A complete manifest only qualifies for manual review; inspect evidence and validate staging configuration before any launch decision."}
    (output_dir / "runner-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report, 0 if report["decision"] == "GO_FOR_MANUAL_REVIEW" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("staging-rehearsal-output"))
    parser.add_argument("--run-id", default="staging-rehearsal-2026-001")
    parser.add_argument("--execute", action="store_true", help="explicitly execute read-only Supabase probes")
    args = parser.parse_args()
    if not _RUN_ID.fullmatch(args.run_id):
        print("NO-GO: invalid run id", file=sys.stderr)
        return 2
    env = dict(os.environ)
    if not args.execute:
        print("NO-GO: pass --execute to run the read-only staging probes; no network request was made.", file=sys.stderr)
        return 2
    if env.get("APP_ENV", "staging").strip().lower() == "production":
        print("NO-GO: refusing to run against APP_ENV=production", file=sys.stderr)
        return 2
    report, code = run_rehearsal(Path(__file__).resolve().parents[1], args.output_dir, env, args.run_id)
    print(json.dumps(report, indent=2))
    return code

if __name__ == "__main__":
    raise SystemExit(main())
