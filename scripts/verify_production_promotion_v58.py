#!/usr/bin/env python3
"""Bind signed staging evidence to the exact source commit and release artifact."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("promotion_gate_v57_for_v58", ROOT / "scripts" / "verify_production_promotion_v57.py")
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load v57 promotion gate")
_gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = _gate
spec.loader.exec_module(_gate)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def evaluate_release(envelope: object, env: dict[str, str] | None = None, *,
                     expected_commit: str | None = None, artifact_sha256: str | None = None,
                     now=None) -> tuple[bool, list[str]]:
    ok, errors = _gate.evaluate_promotion(envelope, env, now=now)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("report"), dict):
        return False, errors + ["signed report is missing"]
    report = envelope["report"]
    commit = report.get("source_commit")
    digest = report.get("artifact_sha256")
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit.lower()):
        errors.append("evidence source_commit must be a full 40-character Git commit SHA")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        errors.append("evidence artifact_sha256 must be a 64-character SHA-256 digest")
    if expected_commit is None:
        errors.append("expected source commit is required")
    elif commit != expected_commit.lower():
        errors.append("evidence source commit does not match requested release commit")
    if artifact_sha256 is None:
        errors.append("release artifact SHA-256 is required")
    elif digest != artifact_sha256.lower():
        errors.append("evidence artifact digest does not match release artifact")
    return not errors, errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("envelope", type=Path, help="signed staging evidence envelope")
    parser.add_argument("--expected-commit", required=True, help="full Git commit SHA to promote")
    parser.add_argument("--artifact", required=True, type=Path, help="exact release artifact to promote")
    parser.add_argument("--report", type=Path, help="write sanitized JSON decision report")
    args = parser.parse_args()
    try:
        envelope = json.loads(args.envelope.read_text(encoding="utf-8"))
        digest = sha256_file(args.artifact)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"NO_GO: input error ({type(exc).__name__})", file=sys.stderr)
        return 2
    ok, errors = evaluate_release(envelope, expected_commit=args.expected_commit.lower(), artifact_sha256=digest)
    result = {"decision": "ELIGIBLE_FOR_MANUAL_REVIEW" if ok else "BLOCKED",
              "automatic_deployment": False, "artifact_sha256": digest, "errors": errors}
    rendered = json.dumps(result, indent=2) + "\\n"
    print(rendered, end="")
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
