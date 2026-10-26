#!/usr/bin/env python3
"""Read-only live staging probe for two authenticated tenants. Never writes data or emits credentials."""
from __future__ import annotations
import argparse, json, os, sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote


def request_status(url: str, token: str, timeout: float = 10.0) -> int:
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"network request failed ({type(exc).__name__})") from None


def evaluate_statuses(health: int, own_a: int, own_b: int, cross_a_to_b: int, cross_b_to_a: int) -> dict:
    checks = {
        "health_endpoint": health == 200,
        "user_a_can_read_own_tenant": own_a == 200,
        "user_b_can_read_own_tenant": own_b == 200,
        "user_a_cannot_read_tenant_b": cross_a_to_b in (403, 404),
        "user_b_cannot_read_tenant_a": cross_b_to_a in (403, 404),
    }
    return {"status": "PASS" if all(checks.values()) else "BLOCKED", "checks": checks,
            "http_statuses": {"health": health, "own_a": own_a, "own_b": own_b,
                              "cross_a_to_b": cross_a_to_b, "cross_b_to_a": cross_b_to_a}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()
    base = os.getenv("STAGING_API_BASE_URL", "").rstrip("/")
    org_a, org_b = os.getenv("STAGING_ORG_A", ""), os.getenv("STAGING_ORG_B", "")
    token_a, token_b = os.getenv("STAGING_USER_A_TOKEN", ""), os.getenv("STAGING_USER_B_TOKEN", "")
    lead_a, lead_b = os.getenv("STAGING_EXISTING_LEAD_A", ""), os.getenv("STAGING_EXISTING_LEAD_B", "")
    missing = [k for k,v in {
        "STAGING_API_BASE_URL":base, "STAGING_ORG_A":org_a, "STAGING_ORG_B":org_b,
        "STAGING_USER_A_TOKEN":token_a, "STAGING_USER_B_TOKEN":token_b,
        "STAGING_EXISTING_LEAD_A":lead_a, "STAGING_EXISTING_LEAD_B":lead_b}.items() if not v]
    if missing:
        print(json.dumps({"status":"BLOCKED","reason":"missing required environment variables","missing":missing}, indent=2))
        return 2
    if org_a == org_b or not base.startswith("https://"):
        print(json.dumps({"status":"BLOCKED","reason":"organizations must differ and base URL must use HTTPS"}, indent=2))
        return 2
    def leads_url(org, lead):
        return f"{base}/api/v1/organizations/{quote(org, safe='')}/leads/{quote(lead, safe='')}"
    try:
        health = request_status(base + "/health", token_a, args.timeout)
        own_a = request_status(leads_url(org_a, lead_a), token_a, args.timeout)
        own_b = request_status(leads_url(org_b, lead_b), token_b, args.timeout)
        cross_a = request_status(leads_url(org_b, lead_b), token_a, args.timeout)
        cross_b = request_status(leads_url(org_a, lead_a), token_b, args.timeout)
    except RuntimeError as exc:
        print(json.dumps({"status":"BLOCKED","reason":str(exc)}, indent=2))
        return 2
    result = evaluate_statuses(health, own_a, own_b, cross_a, cross_b)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
