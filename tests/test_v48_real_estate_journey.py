import json
from pathlib import Path
import subprocess
import sys
import pytest
from app.simulation.real_estate import RealEstateJourney, SimulationBlocked, lead_from_dict

ROOT = Path(__file__).resolve().parents[1]


def qualified_lead(**overrides):
    data = {"lead_id": "lead-1", "organization_id": "agency-a", "consent_to_contact": True,
            "purpose": "buy", "property_type": "apartment", "location": "Braga",
            "budget_max_eur": 250000, "timeline_days": 20, "financing_confirmed": True,
            "visit_requested": True, "visit_slot_available": True}
    data.update(overrides)
    return lead_from_dict(data)


def test_v48_qualified_lead_reaches_simulated_visit_proposal_without_side_effects():
    result = RealEstateJourney("agency-a").process(qualified_lead())
    assert result["state"] == "VISIT_PROPOSED"
    assert result["score"] >= 60
    assert result["simulation_only"] is True
    assert result["external_side_effects"] == 0
    assert any(a["type"] == "PROPOSE_VISIT_SLOT" for a in result["actions"])
    assert all(a["external_side_effect"] is False for a in result["actions"])


def test_v48_missing_consent_never_proposes_outbound_contact():
    result = RealEstateJourney("agency-a").process(qualified_lead(consent_to_contact=False))
    assert result["state"] == "VISIT_PENDING_CONSENT"
    assert not any(a["type"] in {"INITIAL_CONTACT", "DRAFT_INITIAL_MESSAGE", "PROPOSE_VISIT_SLOT", "SCHEDULE_FOLLOW_UP", "SCHEDULE_NURTURE_FOLLOW_UP"} for a in result["actions"])
    assert any(e.get("details", {}).get("reason") == "consent_missing" for e in result["audit"])


def test_v48_do_not_contact_suppresses_contact_even_with_consent():
    result = RealEstateJourney("agency-a").process(qualified_lead(do_not_contact=True))
    assert result["state"] == "VISIT_PENDING_CONSENT"
    assert not any(a["type"] in {"INITIAL_CONTACT", "DRAFT_INITIAL_MESSAGE", "PROPOSE_VISIT_SLOT"} for a in result["actions"])


@pytest.mark.parametrize("extra,reason", [
    ({"requested_discount_percent": 15}, "discount_above_limit"),
    ({"custom_contract": True}, "custom_contract"),
    ({"legal_question": True}, "legal_question"),
    ({"serious_complaint": True}, "serious_complaint"),
    ({"strategic_client": True}, "strategic_client"),
])
def test_v48_sensitive_cases_require_human_approval(extra, reason):
    result = RealEstateJourney("agency-a").process(qualified_lead(**extra))
    assert result["state"] == "HUMAN_APPROVAL_REQUIRED"
    approvals = [a for a in result["actions"] if a["type"] == "HUMAN_REVIEW"]
    assert len(approvals) == 1
    assert reason in approvals[0]["details"]["reasons"]


def test_v48_tenant_mismatch_fails_closed():
    with pytest.raises(SimulationBlocked, match="Tenant mismatch"):
        RealEstateJourney("agency-a").process(qualified_lead(organization_id="agency-b"))


def test_v48_automation_kill_switch_fails_closed():
    with pytest.raises(SimulationBlocked, match="kill switch"):
        RealEstateJourney("agency-a").process(qualified_lead(automation_enabled=False))


def test_v48_reprocessing_does_not_duplicate_same_actions():
    lead = qualified_lead()
    sim = RealEstateJourney("agency-a")
    first = sim.process(lead)
    count = len(lead.actions)
    second = sim.process(lead)
    assert len(lead.actions) == count
    assert second["external_side_effects"] == 0
    assert any(e["event"] == "DUPLICATE_ACTION_SUPPRESSED" for e in lead.audit)
    assert first["actions"] == second["actions"]


def test_v48_cli_runs_example_fixture_and_emits_machine_readable_report(tmp_path):
    output = tmp_path / "report.json"
    completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "simulate_real_estate_golden_path.py"),
                                "--input", str(ROOT / "examples" / "real_estate_leads_v48.json"), "--output", str(output)],
                               cwd=ROOT, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["version"] == 48
    assert report["external_side_effects"] == 0
    assert report["summary"]["leads"] == 3
    assert report["summary"]["pending_approvals"] == 1


def test_v48_rejects_unknown_input_fields():
    with pytest.raises(ValueError, match="Unknown lead fields"):
        lead_from_dict({"lead_id": "x", "organization_id": "agency-a", "send_whatsapp_now": True})
