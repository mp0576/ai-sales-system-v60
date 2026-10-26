#!/usr/bin/env python3
"""Create/verify an HMAC-SHA256 integrity envelope for a staging JSON report.

This proves that the envelope has not changed since signing by a holder of the shared
key. It does not independently prove that the report's claims are true or who ran it.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys

SCHEMA = "staging-evidence-hmac-v1"

def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def get_key(env: dict[str, str] | None = None) -> bytes:
    value = (env or os.environ).get("STAGING_EVIDENCE_HMAC_KEY", "")
    key = value.encode("utf-8")
    if len(key) < 32:
        raise ValueError("STAGING_EVIDENCE_HMAC_KEY must contain at least 32 bytes")
    return key

def sign_report(report: object, key: bytes) -> dict:
    payload = {"schema": SCHEMA, "report": report}
    signature = hmac.new(key, canonical_bytes(payload), hashlib.sha256).hexdigest()
    return {**payload, "signature": {"algorithm": "HMAC-SHA256", "value": signature}}

def verify_envelope(envelope: object, key: bytes) -> tuple[bool, str]:
    if not isinstance(envelope, dict) or envelope.get("schema") != SCHEMA or "report" not in envelope:
        return False, "envelope_schema_invalid"
    signature = envelope.get("signature")
    if not isinstance(signature, dict) or signature.get("algorithm") != "HMAC-SHA256" or not isinstance(signature.get("value"), str):
        return False, "signature_missing_or_invalid"
    payload = {"schema": envelope["schema"], "report": envelope["report"]}
    expected = hmac.new(key, canonical_bytes(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature["value"], expected):
        return False, "signature_mismatch"
    return True, "signature_valid_integrity_only"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="report JSON when signing; signed envelope when --verify")
    parser.add_argument("--output", type=Path, help="output envelope path when signing")
    parser.add_argument("--verify", action="store_true", help="verify an existing signed envelope")
    args = parser.parse_args()
    try:
        key = get_key()
        value = json.loads(args.input.read_text(encoding="utf-8"))
        if args.verify:
            ok, reason = verify_envelope(value, key)
            print(json.dumps({"decision": "PASS" if ok else "NO_GO", "reason": reason}))
            return 0 if ok else 1
        if args.output is None:
            parser.error("--output is required when signing")
        if args.input.resolve() == args.output.resolve():
            parser.error("input and output must be different files")
        envelope = sign_report(value, key)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"decision": "SIGNED", "output": str(args.output), "algorithm": "HMAC-SHA256"}))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"NO_GO: {type(exc).__name__}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
