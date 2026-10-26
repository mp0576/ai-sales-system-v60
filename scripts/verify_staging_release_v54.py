#!/usr/bin/env python3
"""Verify a signed staging evidence envelope and its semantic acceptance checks.

The HMAC protects integrity only; it does not prove that underlying tests were truthful.
No network calls are made. A valid signature alone can never make failed evidence pass.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

_signing = _load_module("sign_staging_evidence_v54", ROOT / "scripts" / "sign_staging_evidence.py")
_acceptance = _load_module("acceptance_evidence_v54", ROOT / "scripts" / "verify_staging_acceptance_v53.py")


def evaluate_envelope(envelope: object, key: bytes, *, now=None) -> tuple[bool, list[str], dict | None]:
    """Return (accepted, errors, report) after signature and policy verification."""
    valid_signature, reason = _signing.verify_envelope(envelope, key)
    if not valid_signature:
        return False, [f"signature verification failed: {reason}"], None
    assert isinstance(envelope, dict)
    report = envelope.get("report")
    errors = _acceptance.validate_evidence(report, now=now)
    return not errors, errors, report if isinstance(report, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("envelope", type=Path, help="HMAC-signed staging evidence envelope")
    parser.add_argument("--report", type=Path, help="optional sanitized Markdown decision report")
    args = parser.parse_args()
    try:
        key = _signing.get_key(dict(os.environ))
        envelope = json.loads(args.envelope.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"NO_GO: input/key error ({type(exc).__name__})", file=sys.stderr)
        return 2
    accepted, errors, evidence = evaluate_envelope(envelope, key)
    status = "ACCEPTED" if accepted else "BLOCKED"
    lines = [
        "# v54 Signed Staging Release Decision", "",
        f"- Decision: **{status}**",
        f"- Signature: {'valid (integrity only)' if not errors or not errors[0].startswith('signature verification failed:') else 'invalid'}",
        f"- Project ref: `{evidence.get('project_ref', 'unknown')}`" if evidence else "- Project ref: unknown",
        f"- Captured at: `{evidence.get('captured_at', 'unknown')}`" if evidence else "- Captured at: unknown",
        "- Live outbound: disabled by acceptance policy",
        "- Live payments: disabled by acceptance policy", "",
    ]
    if errors:
        lines.extend(["## Blocking issues", *[f"- {item}" for item in errors], ""])
    else:
        lines.extend([
            "All semantic acceptance checks passed and the envelope signature is valid.",
            "This verifies integrity and policy compliance only; it cannot independently prove the underlying tests ran.", "",
        ])
    rendered = "\n".join(lines)
    print(rendered)
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    return 0 if accepted else 1

if __name__ == "__main__":
    raise SystemExit(main())
