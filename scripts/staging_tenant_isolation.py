#!/usr/bin/env python3
"""Read-only two-user RLS isolation probe for a dedicated Supabase staging project.

Required environment:
  APP_ENV=staging, SUPABASE_URL, SUPABASE_ANON_KEY,
  STAGING_USER_A_JWT, STAGING_USER_A_ORG_ID,
  STAGING_USER_B_JWT, STAGING_USER_B_ORG_ID

The script issues GET requests only. It does not create records or alter permissions.
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
    url = env.get("SUPABASE_URL", "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        errors.append("SUPABASE_URL must be an HTTPS project origin")
    if not env.get("SUPABASE_ANON_KEY", "").strip():
        errors.append("SUPABASE_ANON_KEY is required")
    if env.get("APP_ENV", "staging").lower() == "production":
        errors.append("This probe is staging-only; refusing APP_ENV=production")
    for suffix in ("A", "B"):
        if not env.get(f"STAGING_USER_{suffix}_JWT", "").strip():
            errors.append(f"STAGING_USER_{suffix}_JWT is required")
        if not env.get(f"STAGING_USER_{suffix}_ORG_ID", "").strip():
            errors.append(f"STAGING_USER_{suffix}_ORG_ID is required")
    if env.get("STAGING_USER_A_ORG_ID", "") == env.get("STAGING_USER_B_ORG_ID", "") and env.get("STAGING_USER_A_ORG_ID"):
        errors.append("User A and User B must belong to different organizations")
    return errors


def _get(client: httpx.Client, base: str, anon_key: str, jwt: str, path: str, params: dict[str, str]):
    return client.get(base + path, headers={"apikey": anon_key, "Authorization": f"Bearer {jwt}", "Accept": "application/json"}, params=params)


def run_checks(env: dict[str, str], *, client: httpx.Client | None = None) -> list[Check]:
    errors = validate_config(env)
    if errors:
        return [Check("configuration", False, "; ".join(errors))]
    base = env["SUPABASE_URL"].strip().rstrip("/")
    anon = env["SUPABASE_ANON_KEY"].strip()
    owned = client is None
    c = client or httpx.Client(timeout=10.0, follow_redirects=False)
    checks: list[Check] = []
    try:
        for suffix, other in (("A", "B"), ("B", "A")):
            jwt = env[f"STAGING_USER_{suffix}_JWT"].strip()
            own_org = env[f"STAGING_USER_{suffix}_ORG_ID"].strip()
            foreign_org = env[f"STAGING_USER_{other}_ORG_ID"].strip()
            try:
                # organizations must include the user's own organization and exclude the other tenant.
                # This catches a false pass caused by an empty leads table.
                org_response = _get(c, base, anon, jwt, "/rest/v1/organizations", {"select": "id", "limit": "1000"})
                if org_response.status_code >= 400:
                    checks.append(Check(f"user_{suffix}_organization_read", False, f"HTTP {org_response.status_code}"))
                    continue
                org_rows = org_response.json()
                if not isinstance(org_rows, list):
                    checks.append(Check(f"user_{suffix}_organization_read", False, "unexpected response shape"))
                    continue
                visible_orgs = {row.get("id") for row in org_rows if isinstance(row, dict)}
                org_ok = own_org in visible_orgs and foreign_org not in visible_orgs
                checks.append(Check(f"user_{suffix}_organization_visibility", org_ok,
                                    f"own_visible={own_org in visible_orgs} foreign_visible={foreign_org in visible_orgs}"))
                if not org_ok:
                    continue

                # An unfiltered request is crucial: if RLS is missing, foreign rows leak here.
                response = _get(c, base, anon, jwt, "/rest/v1/leads", {"select": "organization_id", "limit": "1000"})
                if response.status_code >= 400:
                    checks.append(Check(f"user_{suffix}_lead_read", False, f"HTTP {response.status_code}"))
                    continue
                rows = response.json()
                if not isinstance(rows, list):
                    checks.append(Check(f"user_{suffix}_lead_read", False, "unexpected response shape"))
                    continue
                foreign = [row for row in rows if row.get("organization_id") != own_org]
                checks.append(Check(f"user_{suffix}_unfiltered_rows_tenant_scoped", not foreign,
                                    f"rows={len(rows)} foreign_rows={len(foreign)}"))
                if foreign:
                    continue
                cross = _get(c, base, anon, jwt, "/rest/v1/leads", {
                    "select": "organization_id", "organization_id": f"eq.{foreign_org}", "limit": "1000"
                })
                if cross.status_code >= 400:
                    # 401/403 is an acceptable deny; server errors are not.
                    ok = cross.status_code in (401, 403)
                    checks.append(Check(f"user_{suffix}_foreign_org_query", ok, f"HTTP {cross.status_code}"))
                else:
                    body = cross.json()
                    ok = isinstance(body, list) and len(body) == 0
                    checks.append(Check(f"user_{suffix}_foreign_org_query", ok,
                                        f"HTTP {cross.status_code} rows={len(body) if isinstance(body, list) else 'invalid'}"))
            except (httpx.HTTPError, ValueError):
                checks.append(Check(f"user_{suffix}_rls_probe", False, "request or JSON parsing failed"))
    finally:
        if owned:
            c.close()
    return checks


def main() -> int:
    env = dict(os.environ)
    checks = run_checks(env)
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    if not checks or any(not check.ok for check in checks):
        print("Tenant isolation probe failed. No writes were attempted.", file=sys.stderr)
        return 1
    print("Read-only tenant-isolation probes passed for the supplied staging users; this is not a full security certification.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
