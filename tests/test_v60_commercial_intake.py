import pytest
from fastapi.testclient import TestClient
from app.dashboard import api as api_module
from app.services.public_demo_requests import PublicDemoRequestRepository, IntakeError


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "pilot")
    monkeypatch.setenv("PUBLIC_INTAKE_DATABASE_PATH", str(tmp_path / "intake.sqlite3"))
    monkeypatch.setenv("PUBLIC_INTAKE_ADMIN_TOKEN", "a-very-long-admin-token-for-tests-123")
    api_module._public_intake_repository = None
    with TestClient(api_module.app) as c:
        yield c
    api_module._public_intake_repository = None


def payload(**overrides):
    data = {
        "name": "Ana Silva", "email": "ana@example.pt", "company": "Agência Norte",
        "phone": "", "team_size": "4-10", "monthly_leads": "21-100",
        "notes": "Quer reduzir tempo de resposta.", "consent": True, "website": ""
    }
    data.update(overrides)
    return data


def test_offer_page_and_submission_are_available(client):
    assert client.get("/offer").status_code == 200
    response = client.post("/api/v1/public/demo-requests",
        headers={"Idempotency-Key": "demo-request-key-001"}, json=payload())
    assert response.status_code == 201
    assert response.json()["status"] == "NEW"
    assert response.json()["request_id"].startswith("demo_")


def test_submission_idempotency_and_admin_queue(client):
    headers = {"Idempotency-Key": "demo-request-key-002"}
    first = client.post("/api/v1/public/demo-requests", headers=headers, json=payload())
    replay = client.post("/api/v1/public/demo-requests", headers=headers, json=payload())
    assert first.status_code == replay.status_code == 201
    assert first.json()["request_id"] == replay.json()["request_id"]
    assert replay.json()["replayed"] is True
    denied = client.get("/api/v1/admin/demo-requests")
    assert denied.status_code == 401
    admin = {"Authorization": "Bearer a-very-long-admin-token-for-tests-123"}
    queue = client.get("/api/v1/admin/demo-requests", headers=admin)
    assert queue.status_code == 200 and queue.json()["count"] == 1
    request_id = queue.json()["items"][0]["id"]
    updated = client.patch(f"/api/v1/admin/demo-requests/{request_id}", headers=admin, json={"status":"CONTACTED"})
    assert updated.status_code == 200 and updated.json()["status"] == "CONTACTED"


@pytest.mark.parametrize("overrides", [
    {"consent": False}, {"website": "spam"}, {"team_size": "invalid"},
    {"monthly_leads": "invalid"}, {"email": "not-an-email"}
])
def test_invalid_public_submissions_rejected(client, overrides):
    response = client.post("/api/v1/public/demo-requests",
        headers={"Idempotency-Key": "demo-request-key-invalid"}, json=payload(**overrides))
    assert response.status_code == 422


def test_repository_persists_between_instances(tmp_path):
    db = str(tmp_path / "persistent.sqlite3")
    first = PublicDemoRequestRepository(db)
    item, replay = first.create(payload(), "persist-demo-request-001")
    assert replay is False
    second = PublicDemoRequestRepository(db)
    rows = second.list_requests()
    assert len(rows) == 1 and rows[0]["id"] == item["id"]


def test_email_rate_limit(tmp_path):
    repo = PublicDemoRequestRepository(str(tmp_path / "rate.sqlite3"))
    for i in range(5):
        repo.create(payload(), f"rate-limit-key-{i:03d}")
    with pytest.raises(IntakeError, match="Too many requests"):
        repo.create(payload(), "rate-limit-key-999")
