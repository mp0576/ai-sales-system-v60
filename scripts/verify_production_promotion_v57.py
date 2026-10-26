#!/usr/bin/env python3
"""Fail-closed production promotion gate using signed staging evidence.

This gate does not deploy anything. It only decides whether evidence and safety
flags satisfy policy. HMAC is integrity protection, not proof that tests were truthful.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

_verifier = _load("staging_release_v54_for_v57", ROOT / "scripts" / "verify_staging_release_v54.py")

def evaluate_promotion(envelope: object, env: dict[str, str] | None = None, *, now=None) -> tuple[bool, list[str]]:
    env = dict(os.environ if env is None else env)
    errors: list[str] = []
    try:
        key = _verifier._signing.get_key(env)
    except ValueError:
        return False, ["STAGING_EVIDENCE_HMAC_KEY missing or shorter than 32 bytes"]
    accepted, evidence_errors, report = _verifier.evaluate_envelope(envelope, key, now=now)
    if not accepted:
        errors.extend(evidence_errors or ["staging evidence was not accepted"])
    # Explicit opt-in is required to permit any production side effects later.
    # This v57 gate intentionally requires both switches to remain disabled.
    for name in ("LIVE_OUTBOUND_ENABLED", "LIVE_PAYMENTS_ENABLED"):
        if env.get(name, "").strip().lower() not in ("0", "false", "off", "no"):
            errors.append(f"{name} must be explicitly disabled (0/false/off/no)")
    if report and report.get("environment") not in ("staging", "staging-eu", "staging-us"):
        errors.append("evidence environment must identify staging")
    return not errors, errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("envelope", type=Path, help="signed staging evidence JSON envelope")
    parser.add_argument("--report", type=Path, help="write sanitized decision report")
    args = parser.parse_args()
    try:
        envelope = json.loads(args.envelope.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"NO_GO: evidence input error ({type(exc).__name__})", file=sys.stderr)
        return 2
    accepted, errors = evaluate_promotion(envelope)
    result = {"decision": "ELIGIBLE_FOR_MANUAL_REVIEW" if accepted else "BLOCKED", "automatic_deployment": False, "errors": errors}
    rendered = json.dumps(result, indent=2) + "\n"
    print(rendered, end="")
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    return 0 if accepted else 1

if __name__ == "__main__":
    raise SystemExit(main())
