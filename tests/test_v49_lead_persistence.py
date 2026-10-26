import concurrent.futures
import json
from pathlib import Path
import pytest
from app.repositories.real_estate_leads import LeadConflict, SQLiteLeadRepository


def make_repo(tmp_path):
    return SQLiteLeadRepository(tmp_path / "leads.sqlite3")


def save(repo, *, org="agency-a", lead="lead-1", key="event-1", payload=None, expected=0, state="QUALIFIED"):
    return repo.save_snapshot(organization_id=org, lead_id=lead, state=state,
        payload=payload if payload is not None else {"score": 85}, event_type="SIMULATED_LEAD_PROCESSED",
        idempotency_key=key, expected_version=expected)


def test_v49_snapshot_survives_repository_reopen(tmp_path):
    db = tmp_path / "leads.sqlite3"
    repo = SQLiteLeadRepository(db)
    first = save(repo)
    reopened = SQLiteLeadRepository(db)
    got = reopened.get_lead(organization_id="agency-a", lead_id="lead-1")
    assert first["version"] == 1
    assert got["state"] == "QUALIFIED"
    assert got["payload"] == {"score": 85}


def test_v49_tenant_scoped_reads_do_not_leak_lead_or_events(tmp_path):
    repo = make_repo(tmp_path)
    save(repo, org="agency-a", key="a")
    save(repo, org="agency-b", key="b", payload={"score": 30})
    assert repo.get_lead(organization_id="agency-b", lead_id="lead-1")["payload"]["score"] == 30
    assert repo.get_lead(organization_id="agency-c", lead_id="lead-1") is None
    assert len(repo.list_leads(organization_id="agency-a")) == 1
    assert repo.list_events(organization_id="agency-a", lead_id="lead-1")[0]["event"]["organization_id"] == "agency-a"
    assert repo.list_events(organization_id="agency-b", lead_id="lead-1")[0]["event"]["organization_id"] == "agency-b"


def test_v49_same_idempotency_key_same_request_is_duplicate(tmp_path):
    repo = make_repo(tmp_path)
    first = save(repo)
    second = save(repo)
    assert first["version"] == second["version"] == 1
    assert second["duplicate"] is True
    assert len(repo.list_events(organization_id="agency-a", lead_id="lead-1")) == 1


def test_v49_idempotency_key_reuse_with_different_payload_fails_closed(tmp_path):
    repo = make_repo(tmp_path)
    save(repo)
    with pytest.raises(LeadConflict, match="different request"):
        save(repo, payload={"score": 12})
    assert repo.get_lead(organization_id="agency-a", lead_id="lead-1")["payload"] == {"score": 85}


def test_v49_optimistic_version_prevents_lost_update(tmp_path):
    repo = make_repo(tmp_path)
    save(repo)
    result = repo.save_snapshot(organization_id="agency-a", lead_id="lead-1", state="VISIT_PROPOSED",
        payload={"score": 85, "visit": "simulated"}, event_type="VISIT_PROPOSED",
        idempotency_key="event-2", expected_version=1)
    assert result["version"] == 2
    with pytest.raises(LeadConflict, match="version conflict"):
        repo.save_snapshot(organization_id="agency-a", lead_id="lead-1", state="NURTURE",
            payload={"score": 10}, event_type="STATE_CHANGED", idempotency_key="event-3", expected_version=1)
    assert repo.get_lead(organization_id="agency-a", lead_id="lead-1")["version"] == 2


def test_v49_events_are_append_only_and_ordered_by_version(tmp_path):
    repo = make_repo(tmp_path)
    save(repo)
    repo.save_snapshot(organization_id="agency-a", lead_id="lead-1", state="VISIT_PROPOSED",
        payload={"score": 85}, event_type="VISIT_PROPOSED", idempotency_key="event-2", expected_version=1)
    events = repo.list_events(organization_id="agency-a", lead_id="lead-1")
    assert [e["event"]["version"] for e in events] == [1, 2]
    assert events[0]["event_id"] != events[1]["event_id"]


def test_v49_concurrent_duplicate_claims_write_one_event(tmp_path):
    repo = make_repo(tmp_path)
    def worker():
        return save(repo)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: worker(), range(8)))
    assert sum(not r["duplicate"] for r in results) == 1
    assert len(repo.list_events(organization_id="agency-a", lead_id="lead-1")) == 1


def test_v49_lead_list_is_tenant_scoped_and_limit_bounded(tmp_path):
    repo = make_repo(tmp_path)
    save(repo, lead="lead-a", key="a")
    save(repo, lead="lead-b", key="b")
    assert {x["lead_id"] for x in repo.list_leads(organization_id="agency-a", limit=1)} <= {"lead-a", "lead-b"}
    with pytest.raises(ValueError, match="limit"):
        repo.list_leads(organization_id="agency-a", limit=501)


@pytest.mark.parametrize("kwargs", [
    {"organization_id": "", "lead_id": "x", "state": "NEW", "payload": {}, "idempotency_key": "k"},
    {"organization_id": "org", "lead_id": "x", "state": "NEW", "payload": [], "idempotency_key": "k"},
    {"organization_id": "org", "lead_id": "x", "state": "NEW", "payload": {}, "idempotency_key": ""},
])
def test_v49_invalid_snapshot_inputs_rejected(tmp_path, kwargs):
    repo = make_repo(tmp_path)
    with pytest.raises(ValueError):
        repo.save_snapshot(**kwargs)


def test_v49_idempotency_is_scoped_by_organization(tmp_path):
    repo = make_repo(tmp_path)
    save(repo, org="agency-a", key="same")
    result = save(repo, org="agency-b", key="same", payload={"score": 30})
    assert result["duplicate"] is False
    assert repo.get_lead(organization_id="agency-b", lead_id="lead-1")["payload"]["score"] == 30
