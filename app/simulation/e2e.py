"""Deterministic end-to-end sales lifecycle harness with injectable provider failures."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class E2EState(str, Enum):
    NEW="NEW"; RESEARCHED="RESEARCHED"; CONTACTED="CONTACTED"; QUALIFIED="QUALIFIED"
    OFFER_PRESENTED="OFFER_PRESENTED"; PROPOSAL_SENT="PROPOSAL_SENT"; PAYMENT_PENDING="PAYMENT_PENDING"
    WON="WON"; ONBOARDING="ONBOARDING"; ACTIVE="ACTIVE"; HUMAN_APPROVAL="HUMAN_APPROVAL"
    DO_NOT_CONTACT="DO_NOT_CONTACT"; LOST="LOST"

class E2EBlocked(PermissionError): pass

@dataclass
class E2ELead:
    lead_id: str
    organization_id: str
    state: E2EState = E2EState.NEW
    opt_in: bool = False
    do_not_contact: bool = False
    automation_enabled: bool = True
    outbound_enabled: bool = False
    decision_maker: bool = False
    problem_confirmed: bool = False
    intent: str = "NONE"
    budget_confirmed: bool = False
    score: int = 0
    proposal_id: str | None = None
    customer_id: str | None = None
    payment_verified: bool = False
    processed_webhooks: set[str] = field(default_factory=set)
    idempotency_keys: set[str] = field(default_factory=set)
    events: list[dict[str,Any]] = field(default_factory=list)

class GoldenPath:
    def __init__(self, *, organization_id: str, min_price: float = 449.0, base_price: float = 499.0):
        self.organization_id=organization_id; self.min_price=min_price; self.base_price=base_price
        self._seq=0

    def _event(self, lead:E2ELead, event_type:str, payload:dict[str,Any]|None=None):
        self._seq+=1
        lead.events.append({"seq":self._seq,"organization_id":lead.organization_id,"lead_id":lead.lead_id,"type":event_type,"payload":payload or {}})

    def _check(self, lead:E2ELead):
        if lead.organization_id != self.organization_id: raise E2EBlocked("Tenant mismatch")
        if not lead.automation_enabled: raise E2EBlocked("Automation kill switch is enabled")

    def research(self, lead:E2ELead, *, facts_verified:bool):
        self._check(lead)
        if lead.state != E2EState.NEW: raise RuntimeError("Invalid state for research")
        if not facts_verified: lead.state=E2EState.LOST; self._event(lead,"RESEARCH_UNVERIFIED"); return
        lead.state=E2EState.RESEARCHED; self._event(lead,"RESEARCH_COMPLETED")

    def contact(self, lead:E2ELead, *, provider_ok:bool=True):
        self._check(lead)
        if lead.do_not_contact or not lead.opt_in: raise E2EBlocked("Outbound requires opt-in and no DNC")
        if not lead.outbound_enabled: raise E2EBlocked("Outbound disabled")
        if lead.state != E2EState.RESEARCHED: raise RuntimeError("Lead must be researched before contact")
        if not provider_ok: self._event(lead,"PROVIDER_RETRYABLE_FAILURE",{"provider":"messaging"}); return "RETRY"
        lead.state=E2EState.CONTACTED; self._event(lead,"MESSAGE_SENT"); return "SENT"

    def qualify(self, lead:E2ELead, *, fit:int, problem_confirmed:bool, intent:str, budget_confirmed:bool, decision_maker:bool):
        self._check(lead)
        if lead.state != E2EState.CONTACTED: raise RuntimeError("Lead must be contacted before qualification")
        fit=max(0,min(25,int(fit))); problem=25 if problem_confirmed else 0
        intent_points={"NONE":0,"LOW":5,"MEDIUM":15,"HIGH":30}.get(intent.upper(),0)
        capacity=min(20,(20 if budget_confirmed else 8)+(5 if decision_maker else 0))
        lead.score=fit+problem+intent_points+capacity
        lead.problem_confirmed=problem_confirmed; lead.intent=intent.upper(); lead.budget_confirmed=budget_confirmed; lead.decision_maker=decision_maker
        if lead.score >= 75 and problem_confirmed and decision_maker and intent.upper()=="HIGH":
            lead.state=E2EState.QUALIFIED; self._event(lead,"LEAD_QUALIFIED",{"score":lead.score}); return True
        lead.state=E2EState.LOST; self._event(lead,"LEAD_UNQUALIFIED",{"score":lead.score}); return False

    def present_offer(self, lead:E2ELead):
        self._check(lead)
        if lead.state != E2EState.QUALIFIED: raise RuntimeError("Only qualified leads can receive an offer")
        lead.state=E2EState.OFFER_PRESENTED; self._event(lead,"OFFER_PRESENTED",{"price":self.base_price,"currency":"EUR"})

    def create_proposal(self, lead:E2ELead, *, requested_price:float|None=None, custom_contract:bool=False):
        self._check(lead)
        if lead.state not in (E2EState.OFFER_PRESENTED,): raise RuntimeError("Offer must be presented before proposal")
        if custom_contract: lead.state=E2EState.HUMAN_APPROVAL; self._event(lead,"APPROVAL_REQUIRED",{"reason":"custom_contract"}); return None
        price=self.base_price if requested_price is None else float(requested_price)
        if price < self.min_price:
            lead.state=E2EState.HUMAN_APPROVAL; self._event(lead,"APPROVAL_REQUIRED",{"reason":"price_below_floor","requested_price":price}); return None
        self._seq+=1; lead.proposal_id=f"prop_{self._seq:05d}"; lead.state=E2EState.PROPOSAL_SENT
        self._event(lead,"PROPOSAL_SENT",{"proposal_id":lead.proposal_id,"price":price,"price_locked":True})
        lead.state=E2EState.PAYMENT_PENDING; self._event(lead,"PAYMENT_PENDING")
        return {"proposal_id":lead.proposal_id,"price":price,"currency":"EUR"}

    def payment_webhook(self, lead:E2ELead, *, external_event_id:str, signature_valid:bool, payment_succeeded:bool, organization_id:str):
        self._check(lead)
        if organization_id != self.organization_id or organization_id != lead.organization_id: raise E2EBlocked("Webhook tenant mismatch")
        if not signature_valid: raise E2EBlocked("Invalid webhook signature")
        if external_event_id in lead.processed_webhooks:
            self._event(lead,"DUPLICATE_WEBHOOK_IGNORED",{"external_event_id":external_event_id}); return "DUPLICATE"
        lead.processed_webhooks.add(external_event_id)
        if lead.state != E2EState.PAYMENT_PENDING: raise RuntimeError("Payment event is not valid for current proposal state")
        if not payment_succeeded:
            self._event(lead,"PAYMENT_FAILED",{"external_event_id":external_event_id}); return "FAILED"
        lead.payment_verified=True; lead.state=E2EState.WON; self._event(lead,"PAYMENT_RECEIVED",{"external_event_id":external_event_id,"verified":True})
        lead.customer_id=f"cust_{lead.lead_id}"; lead.state=E2EState.ONBOARDING
        self._event(lead,"CUSTOMER_CREATED",{"customer_id":lead.customer_id}); self._event(lead,"ONBOARDING_STARTED")
        return "PAID"

    def activate(self, lead:E2ELead, *, qa_passed:bool):
        self._check(lead)
        if lead.state != E2EState.ONBOARDING or not lead.payment_verified: raise E2EBlocked("Verified payment and onboarding are required")
        if not qa_passed: self._event(lead,"ONBOARDING_QA_FAILED"); return False
        lead.state=E2EState.ACTIVE; self._event(lead,"ONBOARDING_COMPLETED"); self._event(lead,"CUSTOMER_ACTIVE"); return True
