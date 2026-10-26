import pytest
from app.simulation.e2e import E2EBlocked, E2ELead, E2EState, GoldenPath

def setup_lead():
    sim=GoldenPath(organization_id='org1')
    lead=E2ELead('lead1','org1',opt_in=True,outbound_enabled=True)
    sim.research(lead,facts_verified=True)
    assert sim.contact(lead) == 'SENT'
    return sim,lead

def qualify(sim,lead):
    assert sim.qualify(lead,fit=25,problem_confirmed=True,intent='HIGH',budget_confirmed=True,decision_maker=True)

def test_golden_path_reaches_active_customer_without_human_approval():
    sim,lead=setup_lead(); qualify(sim,lead); sim.present_offer(lead)
    proposal=sim.create_proposal(lead)
    assert proposal['price'] == 499.0 and lead.state == E2EState.PAYMENT_PENDING
    assert sim.payment_webhook(lead,external_event_id='evt_paid_1',signature_valid=True,payment_succeeded=True,organization_id='org1') == 'PAID'
    assert sim.activate(lead,qa_passed=True)
    assert lead.state == E2EState.ACTIVE
    types=[e['type'] for e in lead.events]
    assert types.index('LEAD_QUALIFIED') < types.index('PROPOSAL_SENT') < types.index('PAYMENT_RECEIVED') < types.index('CUSTOMER_ACTIVE')
    assert 'APPROVAL_REQUIRED' not in types

def test_outbound_blocks_without_opt_in_or_with_dnc():
    sim=GoldenPath(organization_id='org1'); no_opt=E2ELead('l1','org1',outbound_enabled=True)
    sim.research(no_opt,facts_verified=True)
    with pytest.raises(E2EBlocked): sim.contact(no_opt)
    dnc=E2ELead('l2','org1',opt_in=True,outbound_enabled=True,do_not_contact=True)
    sim.research(dnc,facts_verified=True)
    with pytest.raises(E2EBlocked): sim.contact(dnc)

def test_outbound_is_disabled_by_default():
    sim=GoldenPath(organization_id='org1'); lead=E2ELead('l1','org1',opt_in=True)
    sim.research(lead,facts_verified=True)
    with pytest.raises(E2EBlocked,match='Outbound disabled'): sim.contact(lead)

def test_retryable_provider_failure_does_not_advance_state():
    sim,lead=setup_lead()
    lead.state=E2EState.RESEARCHED
    result=sim.contact(lead,provider_ok=False)
    assert result == 'RETRY' and lead.state == E2EState.RESEARCHED

def test_tenant_mismatch_blocks_every_stage():
    sim=GoldenPath(organization_id='org1'); lead=E2ELead('l1','org2')
    with pytest.raises(E2EBlocked,match='Tenant mismatch'): sim.research(lead,facts_verified=True)

def test_unverified_research_cannot_be_contacted():
    sim=GoldenPath(organization_id='org1'); lead=E2ELead('l1','org1',opt_in=True,outbound_enabled=True)
    sim.research(lead,facts_verified=False)
    assert lead.state == E2EState.LOST
    with pytest.raises(RuntimeError): sim.contact(lead)

def test_custom_contract_and_below_floor_require_human_approval():
    sim,lead=setup_lead(); qualify(sim,lead); sim.present_offer(lead)
    assert sim.create_proposal(lead,custom_contract=True) is None
    assert lead.state == E2EState.HUMAN_APPROVAL
    sim,lead=setup_lead(); qualify(sim,lead); sim.present_offer(lead)
    assert sim.create_proposal(lead,requested_price=400) is None
    assert lead.state == E2EState.HUMAN_APPROVAL

def test_invalid_webhook_signature_never_marks_paid():
    sim,lead=setup_lead(); qualify(sim,lead); sim.present_offer(lead); sim.create_proposal(lead)
    with pytest.raises(E2EBlocked,match='Invalid webhook signature'):
        sim.payment_webhook(lead,external_event_id='evt1',signature_valid=False,payment_succeeded=True,organization_id='org1')
    assert not lead.payment_verified and lead.state == E2EState.PAYMENT_PENDING

def test_duplicate_webhook_does_not_create_second_customer():
    sim,lead=setup_lead(); qualify(sim,lead); sim.present_offer(lead); sim.create_proposal(lead)
    kwargs=dict(external_event_id='evt1',signature_valid=True,payment_succeeded=True,organization_id='org1')
    assert sim.payment_webhook(lead,**kwargs) == 'PAID'; customer=lead.customer_id
    assert sim.payment_webhook(lead,**kwargs) == 'DUPLICATE'
    assert lead.customer_id == customer
    assert sum(e['type']=='CUSTOMER_CREATED' for e in lead.events) == 1

def test_failed_payment_does_not_create_customer():
    sim,lead=setup_lead(); qualify(sim,lead); sim.present_offer(lead); sim.create_proposal(lead)
    assert sim.payment_webhook(lead,external_event_id='evt_fail',signature_valid=True,payment_succeeded=False,organization_id='org1') == 'FAILED'
    assert lead.customer_id is None and not lead.payment_verified

def test_activation_requires_verified_payment_and_passed_qa():
    sim,lead=setup_lead(); qualify(sim,lead); sim.present_offer(lead); sim.create_proposal(lead)
    with pytest.raises(E2EBlocked): sim.activate(lead,qa_passed=True)
    sim.payment_webhook(lead,external_event_id='evt1',signature_valid=True,payment_succeeded=True,organization_id='org1')
    assert sim.activate(lead,qa_passed=False) is False
    assert lead.state == E2EState.ONBOARDING
    assert sim.activate(lead,qa_passed=True) is True

def test_state_transition_guards_reject_skipping_steps():
    sim=GoldenPath(organization_id='org1'); lead=E2ELead('l1','org1')
    with pytest.raises(RuntimeError): sim.present_offer(lead)
