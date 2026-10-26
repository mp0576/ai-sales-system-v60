import json
import subprocess
import sys
from pathlib import Path
import pytest
from app.pilot.exceptions import build_exception_queue, transition_exception

TS = "2026-10-11T12:00:00Z"
def event(org="agency-a", code="ACTION_FAILED", event_id="evt-1", **extra):
    return {"organization_id": org, "type": code, "event_id": event_id, "timestamp": TS, **extra}

def test_queue_filters_other_tenants_and_omits_pii():
    queue = build_exception_queue([event(email="private@example.com", raw_error="secret provider response"), event(org="agency-b")], "agency-a")
    assert queue["counts"]["total"] == 1
    assert queue["data_quality"]["ignored_other_tenant"] == 1
    rendered = json.dumps(queue)
    assert "private@example.com" not in rendered and "secret provider response" not in rendered

def test_queue_is_deterministic_and_deduplicates_same_source_event():
    ev = event(code="PROVIDER_OUTCOME_UNKNOWN")
    a = build_exception_queue([ev, ev], "agency-a")
    b = build_exception_queue([ev], "agency-a")
    assert a["items"] == b["items"]
    assert a["counts"]["critical"] == 1

def test_distinct_source_events_remain_distinct():
    queue = build_exception_queue([event(event_id="one"), event(event_id="two")], "agency-a")
    assert queue["counts"]["total"] == 2

def test_invalid_timestamp_or_missing_source_id_is_ignored():
    queue = build_exception_queue([event(timestamp="2026-10-11T12:00:00"), event(event_id="")], "agency-a")
    assert queue["items"] == []
    assert queue["data_quality"]["ignored_invalid"] == 2

def test_severity_order_places_critical_first():
    queue = build_exception_queue([event(code="ACTION_FAILED", event_id="a"), event(code="PAYMENT_RECONCILIATION_REQUIRED", event_id="b")], "agency-a")
    assert queue["items"][0]["severity"] == "critical"

def test_non_exception_event_is_ignored():
    assert build_exception_queue([event(code="LEAD_IMPORTED")], "agency-a")["items"] == []

def test_cross_tenant_transition_denied():
    item = build_exception_queue([event()], "agency-a")["items"][0]
    with pytest.raises(PermissionError):
        transition_exception(item, organization_id="agency-b", actor_role="OWNER", action="resolve", actor_id="owner", resolution_note="done")

def test_member_cannot_change_exception_state():
    item = build_exception_queue([event()], "agency-a")["items"][0]
    with pytest.raises(PermissionError):
        transition_exception(item, organization_id="agency-a", actor_role="MEMBER", action="acknowledge", actor_id="member")

def test_assignment_and_acknowledge_require_manager_role():
    item = build_exception_queue([event()], "agency-a")["items"][0]
    assigned = transition_exception(item, organization_id="agency-a", actor_role="MANAGER", action="assign", actor_id="mgr", assigned_to="operator-1")
    acknowledged = transition_exception(assigned, organization_id="agency-a", actor_role="MANAGER", action="acknowledge", actor_id="mgr")
    assert acknowledged["assigned_to"] == "operator-1" and acknowledged["status"] == "ACKNOWLEDGED"

def test_resolve_requires_note_and_terminal_items_cannot_be_reassigned():
    item = build_exception_queue([event()], "agency-a")["items"][0]
    with pytest.raises(ValueError):
        transition_exception(item, organization_id="agency-a", actor_role="ADMIN", action="resolve", actor_id="admin")
    resolved = transition_exception(item, organization_id="agency-a", actor_role="ADMIN", action="resolve", actor_id="admin", resolution_note="Verified provider state; no retry needed.")
    with pytest.raises(ValueError):
        transition_exception(resolved, organization_id="agency-a", actor_role="ADMIN", action="assign", actor_id="admin", assigned_to="operator")

def test_cli_is_read_only_and_outputs_json(tmp_path):
    root = Path(__file__).resolve().parents[1]
    src = tmp_path / "events.jsonl"
    src.write_text(json.dumps(event()) + "\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(root / "scripts/exception_queue.py"), str(src), "--organization-id", "agency-a"], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["counts"]["open"] == 1

def test_cli_rejects_malformed_input_without_partial_output(tmp_path):
    root = Path(__file__).resolve().parents[1]
    src = tmp_path / "events.jsonl"
    src.write_text(json.dumps(event()) + "\nnot-json\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(root / "scripts/exception_queue.py"), str(src), "--organization-id", "agency-a"], capture_output=True, text=True)
    assert result.returncode == 2 and result.stdout == ""

def test_transition_rejects_oversized_resolution_note():
    item = build_exception_queue([event()], "agency-a")["items"][0]
    with pytest.raises(ValueError):
        transition_exception(item, organization_id="agency-a", actor_role="OWNER", action="resolve", actor_id="owner", resolution_note="x" * 501)
