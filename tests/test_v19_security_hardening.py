from pathlib import Path
import httpx
from scripts.staging_tenant_isolation import run_checks, validate_config

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "sql/migrations/0016_rls_privilege_hardening.sql"
BASE_ENV = {
    "APP_ENV": "staging",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "public-test-key",
    "STAGING_USER_A_JWT": "user-a-jwt",
    "STAGING_USER_A_ORG_ID": "org-a",
    "STAGING_USER_B_JWT": "user-b-jwt",
    "STAGING_USER_B_ORG_ID": "org-b",
}


def test_probe_requires_two_distinct_tenants_and_refuses_production():
    assert validate_config(BASE_ENV) == []
    assert any("different organizations" in e for e in validate_config({**BASE_ENV, "STAGING_USER_B_ORG_ID": "org-a"}))
    assert any("staging-only" in e for e in validate_config({**BASE_ENV, "APP_ENV": "production"}))


def test_probe_is_read_only_and_checks_unfiltered_and_cross_tenant_reads():
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params), request.headers.get("authorization")))
        jwt = request.headers.get("authorization")
        own = "org-a" if jwt == "Bearer user-a-jwt" else "org-b"
        if request.url.path.endswith("/organizations"):
            return httpx.Response(200, json=[{"id": own}])
        if request.url.path.endswith("/leads"):
            org_filter = request.url.params.get("organization_id")
            if org_filter:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"organization_id": own}])
        return httpx.Response(404)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        checks = run_checks(BASE_ENV, client=client)
    assert checks and all(c.ok for c in checks)
    assert all(method == "GET" for method, *_ in calls)
    assert len(calls) == 6


def test_probe_detects_foreign_tenant_leak_in_unfiltered_result():
    def handler(request):
        if request.url.path.endswith("/organizations"):
            jwt = request.headers.get("authorization")
            own = "org-a" if jwt == "Bearer user-a-jwt" else "org-b"
            return httpx.Response(200, json=[{"id": own}])
        return httpx.Response(200, json=[{"organization_id": "org-a"}, {"organization_id": "org-b"}])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        checks = run_checks(BASE_ENV, client=client)
    assert any(not c.ok and "foreign_rows=1" in c.detail for c in checks)


def test_probe_never_attempts_network_when_config_invalid():
    checks = run_checks({"APP_ENV": "staging"})
    assert len(checks) == 1 and checks[0].name == "configuration" and not checks[0].ok


def test_migration_removes_client_access_to_outbox_and_action_mutation():
    sql = MIGRATION.read_text().lower()
    assert "revoke all on function public.is_org_member(uuid) from public, anon" in sql
    assert "grant execute on function public.is_org_member(uuid) to authenticated, service_role" in sql
    assert "drop policy if exists outbox_tenant_all" in sql
    assert "drop policy if exists actions_tenant_all" in sql
    assert "create policy actions_member_select" in sql
    assert "revoke all on function public.claim_outbox(integer, text, integer) from public, anon, authenticated" in sql
    assert "grant execute on function public.claim_outbox(integer, text, integer) to service_role" in sql


def test_approval_resolution_checks_role_and_restricts_rpc_grants():
    sql = MIGRATION.read_text().lower()
    assert "security definer" in sql
    assert "upper(m.role) in ('owner', 'admin', 'manager')" in sql
    assert "revoke all on function public.resolve_dashboard_approval(uuid, uuid, boolean, text) from public, anon" in sql
    assert "grant execute on function public.resolve_dashboard_approval(uuid, uuid, boolean, text) to authenticated" in sql
    assert "drop policy if exists dashboard_audit_member_insert" in sql
