from pathlib import Path
import pytest
from app.simulation.e2e import E2EBlocked, E2ELead, E2EState, GoldenPath

ROOT = Path(__file__).resolve().parents[1]


def _qualified_path():
    sim = GoldenPath(organization_id="agency-a")
    lead = E2ELead("lead-29", "agency-a", opt_in=True, outbound_enabled=True)
    sim.research(lead, facts_verified=True)
    assert sim.contact(lead) == "SENT"
    assert sim.qualify(sim_lead := lead, fit=25, problem_confirmed=True,
                       intent="HIGH", budget_confirmed=True, decision_maker=True)
    sim.present_offer(lead)
    return sim, lead


def test_v29_acceptance_protocol_documents_go_no_go_and_live_guards():
    doc = (ROOT / "E2E_ACCEPTANCE_PROTOCOL_V29.md").read_text().lower()
    assert "no-go for live commercial automation" in doc
    assert "two-organization tests" in doc
    assert "live actions disabled" in doc


def test_full_sales_path_is_auditable_and_activates_only_after_verified_payment():
    sim, lead = _qualified_path()
    proposal = sim.create_proposal(lead)
    assert proposal and proposal["price"] == 499.0
    assert lead.state == E2EState.PAYMENT_PENDING
    assert sim.payment_webhook(lead, external_event_id="evt-29-paid", signature_valid=True,
                               payment_succeeded=True, organization_id="agency-a") == "PAID"
    assert sim.activate(lead, qa_passed=True)
    types = [event["type"] for event in lead.events]
    assert types.index("RESEARCH_COMPLETED") < types.index("MESSAGE_SENT")
    assert types.index("LEAD_QUALIFIED") < types.index("PROPOSAL_SENT")
    assert types.index("PAYMENT_RECEIVED") < types.index("CUSTOMER_CREATED") < types.index("CUSTOMER_ACTIVE")
    assert all(event["organization_id"] == "agency-a" for event in lead.events)


def test_v29_rejects_webhook_from_another_organization():
    sim, lead = _qualified_path()
    sim.create_proposal(lead)
    with pytest.raises(E2EBlocked, match="Webhook tenant mismatch"):
        sim.payment_webhook(lead, external_event_id="evt-foreign", signature_valid=True,
                            payment_succeeded=True, organization_id="agency-b")
    assert not lead.payment_verified


def test_v29_repeated_payment_event_is_idempotent():
    sim, lead = _qualified_path()
    sim.create_proposal(lead)
    args = dict(external_event_id="evt-repeat", signature_valid=True,
                payment_succeeded=True, organization_id="agency-a")
    assert sim.payment_webhook(lead, **args) == "PAID"
    customer_id = lead.customer_id
    assert sim.payment_webhook(lead, **args) == "DUPLICATE"
    assert lead.customer_id == customer_id
    assert sum(e["type"] == "CUSTOMER_CREATED" for e in lead.events) == 1


def test_v29_custom_contract_is_not_auto_approved():
    sim, lead = _qualified_path()
    assert sim.create_proposal(lead, custom_contract=True) is None
    assert lead.state == E2EState.HUMAN_APPROVAL
    assert any(e["type"] == "APPROVAL_REQUIRED" for e in lead.events)
