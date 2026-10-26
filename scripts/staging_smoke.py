#!/usr/bin/env python3
"""Read-only connectivity smoke test for a Supabase staging project.

This verifies credentials and basic REST/Auth reachability only. It does not prove
RLS correctness, apply migrations, claim tasks, or perform any write operation.
"""
from __future__ import annotations
import os
import sys
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx

@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def validate_config(env: dict[str, str]) -> list[str]:
    errors: list[str] = []
    raw_url = env.get("SUPABASE_URL", "").strip()
    parsed = urlparse(raw_url)
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append("SUPABASE_URL must be an HTTPS project URL")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        errors.append("SUPABASE_URL must be the project origin without path/query/fragment")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not key:
        errors.append("SUPABASE_SERVICE_ROLE_KEY is required for this backend-only check")
    elif key.startswith("sb_publishable_") or key == env.get("SUPABASE_ANON_KEY", ""):
        errors.append("A server-only service role key is required; public keys are not accepted")
    if env.get("APP_ENV", "staging").lower() == "production":
        errors.append("This script is for staging only; refusing APP_ENV=production")
    return errors


def run_checks(env: dict[str, str], *, client: httpx.Client | None = None) -> list[Check]:
    errors = validate_config(env)
    if errors:
        return [Check("configuration", False, "; ".join(errors))]
    base = env["SUPABASE_URL"].strip().rstrip("/")
    key = env["SUPABASE_SERVICE_ROLE_KEY"].strip()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    owned_client = client is None
    c = client or httpx.Client(timeout=8.0, follow_redirects=False)
    checks: list[Check] = []
    try:
        try:
            response = c.get(base + "/auth/v1/health", headers=headers)
            checks.append(Check("supabase_auth_health", response.status_code < 400,
                                f"HTTP {response.status_code}"))
        except httpx.HTTPError:
            checks.append(Check("supabase_auth_health", False, "network request failed"))
        try:
            # limit=0 is read-only and returns no tenant data; confirms PostgREST can resolve table.
            response = c.get(base + "/rest/v1/organizations", headers=headers,
                             params={"select": "id", "limit": "0"})
            checks.append(Check("organizations_table_read_access", response.status_code < 400,
                                f"HTTP {response.status_code}"))
        except httpx.HTTPError:
            checks.append(Check("organizations_table_read_access", False, "network request failed"))
    finally:
        if owned_client:
            c.close()
    return checks


def main() -> int:
    env = dict(os.environ)
    if env.get("APP_ENV", "staging").lower() == "production":
        print("BLOCKED: staging smoke test refuses APP_ENV=production", file=sys.stderr)
        return 2
    checks = run_checks(env)
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    if not checks or any(not check.ok for check in checks):
        print("Staging smoke test failed. No writes were attempted.", file=sys.stderr)
        return 1
    print("Read-only connectivity checks passed; this is not an RLS or production certification.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
