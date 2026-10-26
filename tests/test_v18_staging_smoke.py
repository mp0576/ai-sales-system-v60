import httpx
from scripts.staging_smoke import run_checks, validate_config

BASE_ENV = {
    "APP_ENV": "staging",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "server-only-test-key-not-a-real-secret",
}

def test_config_rejects_non_https_url():
    assert any("HTTPS" in e for e in validate_config({**BASE_ENV, "SUPABASE_URL": "http://example.supabase.co"}))

def test_config_rejects_public_key():
    env = {**BASE_ENV, "SUPABASE_SERVICE_ROLE_KEY": "sb_publishable_test", "SUPABASE_ANON_KEY": "sb_publishable_test"}
    assert any("public keys" in e for e in validate_config(env))

def test_config_refuses_production_environment():
    assert any("staging only" in e for e in validate_config({**BASE_ENV, "APP_ENV": "production"}))

def test_smoke_passes_auth_and_table_read_checks_without_writes():
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        checks = run_checks(BASE_ENV, client=client)
    assert all(c.ok for c in checks)
    assert [c[0] for c in calls] == ["GET", "GET"]
    assert calls[1][2]["limit"] == "0"

def test_smoke_fails_closed_on_missing_table():
    def handler(request):
        if request.url.path == "/auth/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"message": "not found"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        checks = run_checks(BASE_ENV, client=client)
    assert checks[0].ok is True
    assert checks[1].ok is False

def test_bad_config_never_attempts_network():
    checks = run_checks({"APP_ENV": "staging"})
    assert len(checks) == 1 and checks[0].name == "configuration" and not checks[0].ok
