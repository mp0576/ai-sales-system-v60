#!/usr/bin/env python3
"""Fail-closed preflight for local/pilot configuration; does not prove production readiness."""
from __future__ import annotations
import os
import re
import sys

WEAK_VALUES={"", "changeme", "change-me", "replace-with-a-long-random-secret", "secret", "password", "test-secret"}
def validate(env: dict[str,str]) -> list[str]:
    errors=[]
    token=env.get("DASHBOARD_API_TOKEN", "")
    if token.strip().lower() in WEAK_VALUES or len(token) < 32:
        errors.append("DASHBOARD_API_TOKEN must be a unique random secret of at least 32 characters")
    if env.get("APP_ENV", "pilot").lower() == "production":
        errors.append("This release uses demo in-memory data; production mode is not supported")
    if env.get("ENABLE_LIVE_OUTBOUND", "false").lower() in {"1","true","yes"}:
        errors.append("Live outbound cannot be enabled by this pilot release")
    if env.get("ENABLE_LIVE_PAYMENTS", "false").lower() in {"1","true","yes"}:
        errors.append("Live payment processing cannot be enabled by this pilot release")
    return errors

def main() -> int:
    errors=validate(dict(os.environ))
    if errors:
        for err in errors: print(f"ERROR: {err}",file=sys.stderr)
        return 1
    print("Preflight passed for local/pilot mode only. This is not a production readiness certification.")
    return 0
if __name__ == "__main__": raise SystemExit(main())
