import os
import pytest
from fastapi.testclient import TestClient
from app.dashboard import api as api_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "pilot")
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "test-token-long-enough")
    monkeypatch.setenv("LEAD_DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    api_module._lead_repository = None
    with TestClient(api_module.app) as c:
        yield c
    api_module._lead_repository = None


def headers(**extra):
    return {"Authorization": "Bearer test-token-long-enough", **extra}


def test_v50_lead_api_requires_auth(client):
    response = client.get("/api/v1/organizations/agency-a/leads")
    assert response.status_code == 401


def test_v50_create_read_and_audit_lead(client):
    response = client.post("/api/v1/organizations/agency-a/leads",
        headers=headers(**{"Idempotency-Key": "create-lead-0001"}),
        json={"lead_id":"lead-1","state":"QUALIFIED","payload":{"budget":250000},"expected_version":0})
    assert response.status_code == 200
    assert response.json()["version"] == 1
    got = client.get("/api/v1/organizations/agency-a/leads/lead-1", headers=headers())
    assert got.status_code == 200
    assert got.json()["payload"]["budget"] == 250000
    events = client.get("/api/v1/organizations/agency-a/leads/lead-1/events", headers=headers())
    assert events.status_code == 200
    assert events.json()["count"] == 1


def test_v50_idempotent_replay_does_not_duplicate_event(client):
    body = {"lead_id":"lead-1","state":"NEW","payload":{"source":"web"},"expected_version":0}
    h = headers(**{"Idempotency-Key":"idempotent-lead-0001"})
    first = client.post("/api/v1/organizations/agency-a/leads", headers=h, json=body)
    second = client.post("/api/v1/organizations/agency-a/leads", headers=h, json=body)
    assert first.status_code == second.status_code == 200
    assert second.json()["duplicate"] is True
    events = client.get("/api/v1/organizations/agency-a/leads/lead-1/events", headers=headers())
    assert events.json()["count"] == 1


def test_v50_tenant_scope_isolation(client):
    h = headers(**{"Idempotency-Key":"tenant-a-lead-0001"})
    client.post("/api/v1/organizations/agency-a/leads", headers=h,
        json={"lead_id":"lead-1","state":"NEW","payload":{},"expected_version":0})
    other = client.get("/api/v1/organizations/agency-b/leads/lead-1", headers=headers())
    assert other.status_code == 404


def test_v50_optimistic_version_conflict(client):
    h1 = headers(**{"Idempotency-Key":"version-lead-0001"})
    first = client.post("/api/v1/organizations/agency-a/leads", headers=h1,
        json={"lead_id":"lead-1","state":"NEW","payload":{},"expected_version":0})
    assert first.status_code == 200
    h2 = headers(**{"Idempotency-Key":"version-lead-0002"})
    conflict = client.post("/api/v1/organizations/agency-a/leads", headers=h2,
        json={"lead_id":"lead-1","state":"QUALIFIED","payload":{},"expected_version":0})
    assert conflict.status_code == 409


def test_v50_production_refuses_local_sqlite_fallback(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    # Production auth must be Supabase-backed, so prevent a fake dashboard token from authenticating.
    monkeypatch.setattr(api_module, "supabase_repository", lambda: (_ for _ in ()).throw(api_module.RepositoryError("not configured")))
    response = client.get("/api/v1/organizations/agency-a/leads", headers=headers())
    assert response.status_code == 503
