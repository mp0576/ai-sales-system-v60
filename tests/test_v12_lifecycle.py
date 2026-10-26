from datetime import date, datetime, timezone, timedelta
import pytest
from app.lifecycle.service import (
    CustomerProfile, IntegrationStatus, OnboardingStatus, LifecycleStatus,
    REQUIRED_ONBOARDING_FIELDS, advance_onboarding, activate_customer,
    onboarding_progress, calculate_health_score, assess_customer_risk,
    renewal_reminders, due_renewal_offsets, upsell_eligibility,
    record_event_once, validate_tenant,
)

def complete_profile():
    return {key: ("Example Realty" if key == "company_name" else "https://example.test" if key == "website" else ["residential"] if key == "services" else "value") for key in REQUIRED_ONBOARDING_FIELDS}

def ready_customer():
    return CustomerProfile("cust1","org1",profile=complete_profile(),integrations={k:IntegrationStatus.TESTED for k in ("messaging","calendar","crm")})

def test_onboarding_lists_missing_fields_and_progress():
    p=CustomerProfile("cust1","org1")
    result=advance_onboarding(p,"org1")
    assert result.status == OnboardingStatus.COLLECTING_INFO.value
    assert set(result.missing_fields) == set(REQUIRED_ONBOARDING_FIELDS)
    assert onboarding_progress(p)["percent"] == 0

def test_onboarding_requires_integrations_even_with_complete_profile():
    p=CustomerProfile("cust1","org1",profile=complete_profile())
    result=advance_onboarding(p,"org1")
    assert result.status == OnboardingStatus.CONNECTING.value
    assert set(result.missing_fields) == {"integration:messaging","integration:calendar","integration:crm"}

def test_onboarding_ready_only_after_required_integrations_tested():
    p=ready_customer()
    result=advance_onboarding(p,"org1")
    assert result.status == OnboardingStatus.READY_FOR_ACTIVATION.value
    assert result.events == ("ONBOARDING_CHECKS_PASSED",)

def test_activation_requires_all_qa_checks():
    p=ready_customer()
    result=activate_customer(p,"org1",qa_checks={"inbound_message":True})
    assert result.status == OnboardingStatus.TESTING.value
    assert any(x == "qa:audit_log" for x in result.missing_fields)

def test_activation_happy_path():
    p=ready_customer(); now=datetime(2026,10,9,tzinfo=timezone.utc)
    qa={k:True for k in ("inbound_message","ai_response","crm_write","calendar_booking","followup","audit_log")}
    result=activate_customer(p,"org1",qa_checks=qa,now=now)
    assert result.status == "ACTIVE"
    assert p.lifecycle_status == LifecycleStatus.ACTIVE and p.activated_at == now
    assert "CUSTOMER_ACTIVATED" in result.events

def test_tenant_mismatch_blocks_access():
    with pytest.raises(PermissionError): validate_tenant(ready_customer(),"org2")

def test_health_score_weights_and_validation():
    assert calculate_health_score(usage_score=20,leads_processed_score=10,automation_score=20,outcomes_score=15,engagement_score=10) == 75
    with pytest.raises(ValueError): calculate_health_score(usage_score=26,leads_processed_score=0,automation_score=0,outcomes_score=0,engagement_score=0)

def test_risk_detects_multiple_signals_and_emits_event_once_on_transition():
    p=ready_customer(); p.last_activity_at=datetime(2026,10,1,tzinfo=timezone.utc); p.automation_failures_7d=3; p.usage_drop_percent=60; p.unresolved_issues=1
    now=datetime(2026,10,9,tzinfo=timezone.utc)
    result=assess_customer_risk(p,now=now)
    assert p.lifecycle_status == LifecycleStatus.AT_RISK
    assert len(result.reasons) == 4 and result.events == ("CUSTOMER_AT_RISK",)
    again=assess_customer_risk(p,now=now)
    assert again.events == ()

def test_risk_can_clear_when_signals_disappear():
    p=ready_customer(); p.lifecycle_status=LifecycleStatus.AT_RISK; p.last_activity_at=datetime(2026,10,8,tzinfo=timezone.utc)
    result=assess_customer_risk(p,now=datetime(2026,10,9,tzinfo=timezone.utc))
    assert p.lifecycle_status == LifecycleStatus.ACTIVE
    assert result.events == ("CUSTOMER_RISK_CLEARED",)

def test_renewal_reminders_and_exact_due_offsets():
    today=date(2026,10,9); renewal=date(2026,11,8)
    assert renewal_reminders(renewal,today=today) == (date(2026,10,9),date(2026,10,25),date(2026,11,1))
    assert due_renewal_offsets(renewal,today=today) == (30,)

def test_upsell_requires_value_and_confirmed_need():
    assert upsell_eligibility(active_days=60,confirmed_need=True,outcome_proven=True) == (True,"ELIGIBLE")
    assert upsell_eligibility(active_days=60,confirmed_need=True,outcome_proven=False)[0] is False
    assert upsell_eligibility(active_days=60,confirmed_need=True,outcome_proven=True,unresolved_critical_issue=True)[0] is False

def test_event_idempotency():
    p=ready_customer()
    assert record_event_once(p,"evt-1") is True
    assert record_event_once(p,"evt-1") is False
    with pytest.raises(ValueError): record_event_once(p,"")
