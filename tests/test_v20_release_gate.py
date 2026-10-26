from pathlib import Path
from app.release.gate import run_gate, staging_config_checks, static_checks

ROOT = Path(__file__).resolve().parents[1]


def good_env():
    return {
        "APP_ENV": "staging",
        "SUPABASE_URL": "https://example-project.supabase.co",
        "SUPABASE_ANON_KEY": "public-anon-key",
        "SUPABASE_SERVICE_ROLE_KEY": "server-only-secret-key",
        "DASHBOARD_API_TOKEN": "a" * 48,
        "OUTBOUND_ENABLED": "false",
        "ENABLE_LIVE_PAYMENTS": "false",
    }


def test_static_release_gate_passes_repository_contracts():
    checks = static_checks(ROOT)
    assert checks
    assert all(check.passed for check in checks), [(c.name, c.detail) for c in checks if not c.passed]


def test_valid_staging_configuration_passes():
    checks = staging_config_checks(good_env())
    assert all(check.passed for check in checks), [(c.name, c.detail) for c in checks if not c.passed]


def test_production_environment_is_not_accepted_by_staging_gate():
    env = good_env() | {"APP_ENV": "production"}
    checks = staging_config_checks(env)
    assert not next(c for c in checks if c.name == "staging_environment").passed


def test_rejects_non_https_supabase_url():
    env = good_env() | {"SUPABASE_URL": "http://example-project.supabase.co"}
    checks = staging_config_checks(env)
    assert not next(c for c in checks if c.name == "supabase_https_origin").passed


def test_rejects_same_public_and_service_key():
    env = good_env() | {"SUPABASE_SERVICE_ROLE_KEY": "public-anon-key"}
    checks = staging_config_checks(env)
    assert not next(c for c in checks if c.name == "supabase_keys_distinct").passed


def test_rejects_weak_dashboard_token():
    env = good_env() | {"DASHBOARD_API_TOKEN": "changeme"}
    checks = staging_config_checks(env)
    assert not next(c for c in checks if c.name == "dashboard_token_strength").passed


def test_rejects_live_actions_in_staging():
    env = good_env() | {"OUTBOUND_ENABLED": "true"}
    checks = staging_config_checks(env)
    assert not next(c for c in checks if c.name == "live_actions_disabled").passed


def test_full_gate_fails_closed_without_external_credentials():
    checks = run_gate(ROOT, {}, include_staging=True)
    assert any(not c.passed for c in checks)
