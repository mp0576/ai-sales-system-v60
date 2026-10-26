from scripts.staging_readonly_probe_v55 import evaluate_statuses


def test_probe_passes_when_both_tenants_are_isolated():
    result = evaluate_statuses(200, 200, 200, 403, 404)
    assert result["status"] == "PASS"
    assert all(result["checks"].values())


def test_probe_fails_when_cross_tenant_request_succeeds():
    result = evaluate_statuses(200, 200, 200, 200, 404)
    assert result["status"] == "BLOCKED"
    assert not result["checks"]["user_a_cannot_read_tenant_b"]


def test_probe_fails_when_own_tenant_unavailable():
    result = evaluate_statuses(200, 404, 200, 403, 403)
    assert result["status"] == "BLOCKED"


def test_probe_fails_when_health_is_unavailable():
    assert evaluate_statuses(503, 200, 200, 403, 403)["status"] == "BLOCKED"
