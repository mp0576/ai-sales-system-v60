#!/usr/bin/env python3
"""Run repository release checks and optional staging configuration checks.

Usage:
  python scripts/release_gate.py --static-only
  APP_ENV=staging ... python scripts/release_gate.py

No network calls are made. A passing result is not a live service certification.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.release.gate import run_gate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-only", action="store_true", help="skip environment/staging config checks")
    args = parser.parse_args()
    checks = run_gate(ROOT, dict(os.environ), include_staging=not args.static_only)
    for item in checks:
        print(f"{'PASS' if item.passed else 'BLOCK'} {item.name}: {item.detail}")
    failed = [item for item in checks if item.blocking and not item.passed]
    if failed:
        print(f"RELEASE BLOCKED: {len(failed)} blocking check(s) failed. No network calls or writes were made.", file=sys.stderr)
        return 1
    print("Static/configuration gate passed. This does not prove live RLS, RPC grants, worker behavior, or provider sandbox results.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
