import json
import subprocess
import sys
from pathlib import Path
import pytest
from app.pilot.monitoring import build_daily_report

DAY = "2026-10-11"
def ev(org="agency-a", typ="LEAD_IMPORTED", ts="2026-10-11T12:00:00Z", **extra):
    return {"organization_id": org, "type": typ, "timestamp": ts, **extra}

def test_daily_report_only_includes_selected_tenant_and_date():
    report = build_daily_report([ev(), ev(org="agency-b"), ev(ts="2026-10-10T23:59:59Z")], "agency-a", DAY)
    assert report["event_count"] == 1
    assert report["data_quality"]["events_ignored_other_tenant"] == 1

def test_unknown_provider_outcome_raises_critical_alert():
    report = build_daily_report([ev(typ="PROVIDER_OUTCOME_UNKNOWN")], "agency-a", DAY)
    assert report["alerts"] == [{"severity": "critical", "code": "PROVIDER_OUTCOME_UNKNOWN", "count": 1}]

def test_failed_action_raises_high_alert():
    report = build_daily_report([ev(typ="ACTION_FAILED")], "agency-a", DAY)
    assert report["alerts"][0]["severity"] == "high"

def test_intervention_rate_alert_uses_imported_denominator():
    report = build_daily_report([ev(), ev(typ="HUMAN_INTERVENTION")], "agency-a", DAY, max_human_intervention_rate=0.4)
    assert report["alerts"][0]["code"] == "HUMAN_INTERVENTION_RATE_HIGH"

def test_pii_is_never_emitted_in_report():
    report = build_daily_report([ev(name="PRIVATE NAME", email="private@example.com", phone="123")], "agency-a", DAY)
    rendered = json.dumps(report)
    assert "PRIVATE NAME" not in rendered and "private@example.com" not in rendered and '"phone"' not in rendered

def test_timezone_naive_timestamp_is_ignored_fail_closed():
    report = build_daily_report([ev(ts="2026-10-11T12:00:00")], "agency-a", DAY)
    assert report["event_count"] == 0
    assert report["data_quality"]["events_ignored_missing_or_invalid_timezone_timestamp"] == 1

def test_invalid_date_and_thresholds_rejected():
    with pytest.raises(ValueError): build_daily_report([], "agency-a", "yesterday")
    with pytest.raises(ValueError): build_daily_report([], "agency-a", DAY, max_human_intervention_rate=1.1)

def test_empty_report_is_zero_safe():
    report = build_daily_report([], "agency-a", DAY)
    assert report["metrics"]["response_rate"] == 0.0
    assert report["alerts"] == []

def test_daily_report_cli_is_read_only_and_outputs_json(tmp_path):
    root = Path(__file__).resolve().parents[1]
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps(ev()) + "\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(root / "scripts/daily_pilot_report.py"), str(events), "--organization-id", "agency-a", "--date", DAY], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["event_count"] == 1

def test_malformed_jsonl_fails_without_partial_report(tmp_path):
    root = Path(__file__).resolve().parents[1]
    events = tmp_path / "events.jsonl"
    events.write_text('{"type":"LEAD_IMPORTED"}\nnot-json\n', encoding="utf-8")
    result = subprocess.run([sys.executable, str(root / "scripts/daily_pilot_report.py"), str(events), "--organization-id", "agency-a", "--date", DAY], capture_output=True, text=True)
    assert result.returncode == 2
    assert result.stdout == ""

def test_monitoring_pack_in_release_gate():
    from app.release.gate import static_checks
    root = Path(__file__).resolve().parents[1]
    checks = {item.name: item for item in static_checks(root)}
    assert checks["pilot_monitoring_pack"].passed
