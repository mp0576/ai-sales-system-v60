"""Customer onboarding, health, risk and renewal lifecycle rules.

Pure deterministic rules: production persistence/scheduling is delegated to repositories and workers.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any

class OnboardingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COLLECTING_INFO = "COLLECTING_INFO"
    CONNECTING = "CONNECTING"
    TESTING = "TESTING"
    READY_FOR_ACTIVATION = "READY_FOR_ACTIVATION"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"

class IntegrationStatus(str, Enum):
    NOT_CONNECTED = "NOT_CONNECTED"
    AUTH_PENDING = "AUTH_PENDING"
    CONNECTED = "CONNECTED"
    TESTED = "TESTED"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"

class LifecycleStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    RENEWAL_DUE = "RENEWAL_DUE"
    CHURNED = "CHURNED"

REQUIRED_ONBOARDING_FIELDS = (
    "company_name", "website", "services", "target_customer", "sales_process",
    "business_hours", "preferred_channel", "notification_contact",
)
REQUIRED_INTEGRATIONS = ("messaging", "calendar", "crm")

@dataclass
class CustomerProfile:
    customer_id: str
    organization_id: str
    onboarding_status: OnboardingStatus = OnboardingStatus.NOT_STARTED
    lifecycle_status: LifecycleStatus = LifecycleStatus.ONBOARDING
    profile: dict[str, Any] = field(default_factory=dict)
    integrations: dict[str, IntegrationStatus] = field(default_factory=dict)
    health_score: int = 0
    last_activity_at: datetime | None = None
    activated_at: datetime | None = None
    unresolved_issues: int = 0
    automation_failures_7d: int = 0
    usage_drop_percent: float = 0.0
    renewal_date: date | None = None
    event_keys: set[str] = field(default_factory=set)

@dataclass(frozen=True)
class LifecycleResult:
    status: str
    events: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

class LifecycleError(ValueError):
    pass

def validate_tenant(profile: CustomerProfile, organization_id: str) -> None:
    if not organization_id or profile.organization_id != organization_id:
        raise PermissionError("Customer tenant mismatch")

def missing_onboarding_fields(profile: CustomerProfile) -> tuple[str, ...]:
    missing=[]
    for key in REQUIRED_ONBOARDING_FIELDS:
        value=profile.profile.get(key)
        if value is None or (isinstance(value, str) and not value.strip()) or value == []:
            missing.append(key)
    return tuple(missing)

def onboarding_progress(profile: CustomerProfile) -> dict[str, Any]:
    missing=missing_onboarding_fields(profile)
    integrations={k: profile.integrations.get(k, IntegrationStatus.NOT_CONNECTED).value for k in REQUIRED_INTEGRATIONS}
    integrations_ready=all(profile.integrations.get(k) in (IntegrationStatus.TESTED, IntegrationStatus.ACTIVE) for k in REQUIRED_INTEGRATIONS)
    checks=[not missing, integrations_ready]
    return {"customer_id":profile.customer_id,"organization_id":profile.organization_id,
            "status":profile.onboarding_status.value,"missing_fields":list(missing),
            "integrations":integrations,"percent":round(100*sum(checks)/len(checks)),
            "ready_to_activate":not missing and integrations_ready}

def advance_onboarding(profile: CustomerProfile, organization_id: str) -> LifecycleResult:
    validate_tenant(profile, organization_id)
    missing=missing_onboarding_fields(profile)
    if missing:
        profile.onboarding_status=OnboardingStatus.COLLECTING_INFO
        return LifecycleResult(profile.onboarding_status.value, missing_fields=missing)
    profile.onboarding_status=OnboardingStatus.CONNECTING
    not_ready=[k for k in REQUIRED_INTEGRATIONS if profile.integrations.get(k) not in (IntegrationStatus.TESTED,IntegrationStatus.ACTIVE)]
    if not_ready:
        return LifecycleResult(profile.onboarding_status.value, missing_fields=tuple(f"integration:{x}" for x in not_ready))
    profile.onboarding_status=OnboardingStatus.READY_FOR_ACTIVATION
    return LifecycleResult(profile.onboarding_status.value, events=("ONBOARDING_CHECKS_PASSED",))

def activate_customer(profile: CustomerProfile, organization_id: str, *, qa_checks: dict[str, bool], now: datetime | None = None) -> LifecycleResult:
    validate_tenant(profile, organization_id)
    missing=missing_onboarding_fields(profile)
    integrations_ready=all(profile.integrations.get(k) in (IntegrationStatus.TESTED,IntegrationStatus.ACTIVE) for k in REQUIRED_INTEGRATIONS)
    failed=tuple(k for k,v in qa_checks.items() if not v)
    required_qa=("inbound_message", "ai_response", "crm_write", "calendar_booking", "followup", "audit_log")
    missing_qa=tuple(f"qa:{k}" for k in required_qa if k not in qa_checks or not qa_checks[k])
    if missing or not integrations_ready or missing_qa:
        profile.onboarding_status=OnboardingStatus.BLOCKED if failed else OnboardingStatus.TESTING
        return LifecycleResult(profile.onboarding_status.value, missing_fields=missing+tuple(f"integration:{k}" for k in REQUIRED_INTEGRATIONS if profile.integrations.get(k) not in (IntegrationStatus.TESTED,IntegrationStatus.ACTIVE))+missing_qa)
    profile.onboarding_status=OnboardingStatus.ACTIVE
    profile.lifecycle_status=LifecycleStatus.ACTIVE
    profile.activated_at=now or datetime.now(timezone.utc)
    profile.last_activity_at=profile.activated_at
    profile.health_score=max(profile.health_score, 60)
    return LifecycleResult("ACTIVE",events=("ONBOARDING_COMPLETED","CUSTOMER_ACTIVATED"))

def calculate_health_score(*, usage_score: int, leads_processed_score: int, automation_score: int, outcomes_score: int, engagement_score: int) -> int:
    parts=((usage_score,25),(leads_processed_score,20),(automation_score,20),(outcomes_score,20),(engagement_score,15))
    if any(not isinstance(v,int) or v < 0 or v > cap for v,cap in parts):
        raise ValueError("Health score component outside allowed range")
    return sum(v for v,_ in parts)

def assess_customer_risk(profile: CustomerProfile, *, now: datetime | None = None) -> LifecycleResult:
    now=now or datetime.now(timezone.utc)
    reasons=[]
    if profile.last_activity_at and now - profile.last_activity_at > timedelta(days=7): reasons.append("NO_ACTIVITY_7D")
    if profile.automation_failures_7d >= 3: reasons.append("AUTOMATION_FAILURES_3PLUS")
    if profile.usage_drop_percent >= 50: reasons.append("USAGE_DROP_50_PERCENT")
    if profile.unresolved_issues > 0: reasons.append("UNRESOLVED_ISSUES")
    events=[]
    if reasons and profile.lifecycle_status not in (LifecycleStatus.CHURNED, LifecycleStatus.AT_RISK):
        profile.lifecycle_status=LifecycleStatus.AT_RISK
        events.append("CUSTOMER_AT_RISK")
    elif not reasons and profile.lifecycle_status == LifecycleStatus.AT_RISK:
        profile.lifecycle_status=LifecycleStatus.ACTIVE
        events.append("CUSTOMER_RISK_CLEARED")
    return LifecycleResult(profile.lifecycle_status.value,events=tuple(events),reasons=tuple(reasons))

def renewal_reminders(renewal_date: date, *, offsets: tuple[int,...]=(90,60,30,14,7), today: date | None=None) -> tuple[date,...]:
    today=today or date.today()
    return tuple(renewal_date-timedelta(days=n) for n in offsets if renewal_date-timedelta(days=n) >= today)

def due_renewal_offsets(renewal_date: date, *, today: date | None=None, offsets: tuple[int,...]=(90,60,30,14,7)) -> tuple[int,...]:
    today=today or date.today()
    days=(renewal_date-today).days
    return tuple(offset for offset in offsets if days == offset)

def upsell_eligibility(*, active_days: int, confirmed_need: bool, outcome_proven: bool, unresolved_critical_issue: bool=False) -> tuple[bool,str]:
    if unresolved_critical_issue: return False,"CRITICAL_ISSUE_OPEN"
    if not confirmed_need: return False,"NEED_NOT_CONFIRMED"
    if not outcome_proven: return False,"VALUE_NOT_YET_PROVEN"
    if active_days < 30: return False,"MINIMUM_TENURE_NOT_MET"
    return True,"ELIGIBLE"

def record_event_once(profile: CustomerProfile, event_key: str) -> bool:
    if not event_key: raise ValueError("event key is required")
    if event_key in profile.event_keys: return False
    profile.event_keys.add(event_key)
    return True
