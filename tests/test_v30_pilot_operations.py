from app.pilot.lead_import import validate_csv
from app.pilot.metrics import calculate_pilot_metrics

HEADER = "organization_id,external_id,name,email,phone,source,consent_status,consent_at\n"

def test_valid_opt_in_lead_is_contactable_only_with_timestamp():
    report = validate_csv(HEADER + "agency-a,1,Alice,alice@example.com,+331234,website,opt_in,2026-10-01T10:00:00Z\n", "agency-a")
    assert report.valid_count == 1
    assert report.accepted[0].contactable
    assert not report.rejected

def test_opt_out_is_retained_but_never_contactable():
    report = validate_csv(HEADER + "agency-a,1,Alice,alice@example.com,+331234,website,opt_out,\n", "agency-a")
    assert report.valid_count == 1
    assert not report.accepted[0].contactable
    assert report.non_contactable == ["1"]

def test_unknown_consent_is_not_contactable():
    report = validate_csv(HEADER + "agency-a,1,Alice,alice@example.com,+331234,website,unknown,\n", "agency-a")
    assert not report.accepted[0].contactable

def test_cross_tenant_row_rejected():
    report = validate_csv(HEADER + "agency-b,1,Alice,alice@example.com,+331234,website,opt_in,2026-10-01T10:00:00Z\n", "agency-a")
    assert report.valid_count == 0
    assert report.rejected[0]["reason"] == "organization_mismatch"

def test_opt_in_without_valid_timestamp_rejected():
    report = validate_csv(HEADER + "agency-a,1,Alice,alice@example.com,+331234,website,opt_in,yesterday\n", "agency-a")
    assert report.rejected[0]["reason"] == "opt_in_requires_valid_consent_timestamp"

def test_invalid_email_rejected():
    report = validate_csv(HEADER + "agency-a,1,Alice,nope,+331234,website,unknown,\n", "agency-a")
    assert report.rejected[0]["reason"] == "invalid_email"

def test_duplicate_contact_is_reported():
    rows = "agency-a,1,Alice,alice@example.com,+331234,website,unknown,\nagency-a,2,Ally,ALICE@example.com,+339999,crm,unknown,\n"
    report = validate_csv(HEADER + rows, "agency-a")
    assert report.valid_count == 1
    assert len(report.duplicates) == 1

def test_missing_columns_fail_closed():
    report = validate_csv("organization_id,name\nagency-a,Alice\n", "agency-a")
    assert report.valid_count == 0
    assert report.rejected[0]["reason"] == "missing_columns"

def test_metrics_rates_handle_empty_denominators():
    metrics = calculate_pilot_metrics([])
    assert metrics["response_rate"] == 0.0
    assert metrics["qualification_rate_from_contacted"] == 0.0
    assert metrics["human_intervention_rate"] == 0.0

def test_metrics_calculate_funnel_and_safety_counts():
    metrics = calculate_pilot_metrics([
        {"type": "LEAD_IMPORTED"}, {"type": "LEAD_IMPORTED"},
        {"type": "FIRST_RESPONSE_SENT"}, {"type": "LEAD_QUALIFIED"},
        {"type": "VISIT_BOOKED"}, {"type": "HUMAN_INTERVENTION"},
        {"type": "PROVIDER_OUTCOME_UNKNOWN"}, {"type": "ACTION_FAILED"},
        {"type": "DUPLICATE_SUPPRESSED"},
    ])
    assert metrics["response_rate"] == 0.5
    assert metrics["qualification_rate_from_contacted"] == 1.0
    assert metrics["booking_rate_from_qualified"] == 1.0
    assert metrics["human_intervention_rate"] == 0.5
    assert metrics["provider_unknown_outcomes"] == 1
    assert metrics["failed_actions"] == 1
    assert metrics["duplicate_suppressed"] == 1

def test_pilot_operations_pack_is_part_of_static_release_gate():
    from pathlib import Path
    from app.release.gate import static_checks
    root = Path(__file__).resolve().parents[1]
    checks = {check.name: check for check in static_checks(root)}
    assert checks["pilot_operations_pack"].passed
