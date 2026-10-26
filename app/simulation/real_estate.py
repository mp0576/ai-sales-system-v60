"""Offline, deterministic real-estate lead journey simulation (no external side effects)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any


class SimulationBlocked(PermissionError):
    """Raised when tenant or execution guardrails fail closed."""


@dataclass
class RealEstateLead:
    lead_id: str
    organization_id: str
    source: str = "website"
    consent_to_contact: bool = False
    do_not_contact: bool = False
    property_type: str = "unknown"
    purpose: str = "unknown"  # buy, rent, sell, let
    location: str = "unknown"
    budget_min_eur: int | None = None
    budget_max_eur: int | None = None
    timeline_days: int | None = None
    financing_confirmed: bool = False
    visit_requested: bool = False
    visit_slot_available: bool = False
    requested_discount_percent: float = 0.0
    custom_contract: bool = False
    legal_question: bool = False
    serious_complaint: bool = False
    strategic_client: bool = False
    automation_enabled: bool = True
    outbound_enabled: bool = False
    state: str = "NEW"
    score: int = 0
    actions: list[dict[str, Any]] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)
    idempotency_keys: set[str] = field(default_factory=set)


class RealEstateJourney:
    """A deterministic simulation. It never calls messaging, calendar, CRM or payment providers."""
    def __init__(self, organization_id: str, *, discount_auto_limit_percent: float = 10.0):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id
        self.discount_auto_limit_percent = discount_auto_limit_percent

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _record(self, lead: RealEstateLead, event: str, details: dict[str, Any] | None = None) -> None:
        body = {"organization_id": lead.organization_id, "lead_id": lead.lead_id,
                "event": event, "details": details or {}}
        body["event_id"] = sha256(self._canonical(body).encode()).hexdigest()[:24]
        lead.audit.append(body)

    def _action(self, lead: RealEstateLead, action_type: str, status: str,
                details: dict[str, Any] | None = None) -> None:
        key_material = {"organization_id": lead.organization_id, "lead_id": lead.lead_id,
                        "action_type": action_type, "details": details or {}}
        key = sha256(self._canonical(key_material).encode()).hexdigest()
        if key in lead.idempotency_keys:
            self._record(lead, "DUPLICATE_ACTION_SUPPRESSED", {"action_type": action_type, "idempotency_key": key})
            return
        lead.idempotency_keys.add(key)
        item = {"action_id": key[:24], "idempotency_key": key, "type": action_type,
                "status": status, "details": details or {}, "external_side_effect": False}
        lead.actions.append(item)
        self._record(lead, "ACTION_" + status, {"action_id": item["action_id"], "type": action_type})

    def process(self, lead: RealEstateLead) -> dict[str, Any]:
        if lead.organization_id != self.organization_id:
            raise SimulationBlocked("Tenant mismatch")
        if not lead.lead_id.strip():
            raise ValueError("lead_id is required")
        if not lead.automation_enabled:
            raise SimulationBlocked("Automation kill switch is enabled")
        start_actions = len(lead.actions)
        self._record(lead, "LEAD_RECEIVED", {"source": lead.source})
        lead.state = "RESEARCHED"
        self._action(lead, "RESEARCH_LEAD", "SIMULATED", {"location": lead.location, "property_type": lead.property_type})

        # Contact permission is explicit: no consent or DNC means no outbound action.
        if lead.do_not_contact:
            lead.state = "DO_NOT_CONTACT"
            self._record(lead, "CONTACT_SUPPRESSED", {"reason": "do_not_contact"})
        elif not lead.consent_to_contact:
            lead.state = "WAITING_FOR_CONSENT"
            self._record(lead, "CONTACT_SUPPRESSED", {"reason": "consent_missing"})
        elif not lead.outbound_enabled:
            lead.state = "READY_FOR_CONTACT"
            self._action(lead, "DRAFT_INITIAL_MESSAGE", "SIMULATED", {"requires_live_outbound_flag": True})
        else:
            # Even if a fixture says enabled, this simulator never sends anything.
            self._action(lead, "INITIAL_CONTACT", "SIMULATED_ONLY", {"live_send_performed": False})
            lead.state = "CONTACT_SIMULATED"

        score = 0
        if lead.purpose.lower() in {"buy", "rent", "sell", "let"}: score += 15
        if lead.property_type.lower() not in {"", "unknown"}: score += 10
        if lead.location.lower() not in {"", "unknown"}: score += 15
        if lead.budget_max_eur is not None and lead.budget_max_eur > 0: score += 20
        if lead.timeline_days is not None and 0 <= lead.timeline_days <= 90: score += 20
        if lead.financing_confirmed: score += 10
        if lead.visit_requested: score += 10
        lead.score = min(score, 100)
        self._record(lead, "LEAD_SCORED", {"score": lead.score})

        high_risk_reasons = []
        if lead.requested_discount_percent > self.discount_auto_limit_percent: high_risk_reasons.append("discount_above_limit")
        if lead.custom_contract: high_risk_reasons.append("custom_contract")
        if lead.legal_question: high_risk_reasons.append("legal_question")
        if lead.serious_complaint: high_risk_reasons.append("serious_complaint")
        if lead.strategic_client: high_risk_reasons.append("strategic_client")
        if high_risk_reasons:
            lead.state = "HUMAN_APPROVAL_REQUIRED"
            self._action(lead, "HUMAN_REVIEW", "PENDING_APPROVAL", {"reasons": high_risk_reasons})
        elif lead.score >= 60:
            lead.state = "QUALIFIED"
            self._action(lead, "PREPARE_PROPERTY_SHORTLIST", "SIMULATED", {"score": lead.score})
            if lead.visit_requested:
                if lead.do_not_contact or not lead.consent_to_contact:
                    lead.state = "VISIT_PENDING_CONSENT"
                    self._record(lead, "VISIT_CONTACT_SUPPRESSED", {"reason": "do_not_contact" if lead.do_not_contact else "consent_missing"})
                elif lead.visit_slot_available:
                    self._action(lead, "PROPOSE_VISIT_SLOT", "SIMULATED", {"availability_confirmed_in_simulation": True})
                    lead.state = "VISIT_PROPOSED"
                else:
                    self._action(lead, "REQUEST_VISIT_AVAILABILITY", "SIMULATED", {"calendar_provider_called": False})
                    lead.state = "VISIT_PENDING_AVAILABILITY"
            elif lead.consent_to_contact and not lead.do_not_contact:
                self._action(lead, "SCHEDULE_FOLLOW_UP", "SIMULATED", {"next_step": "confirm_preferences"})
        else:
            lead.state = "NURTURE"
            if lead.consent_to_contact and not lead.do_not_contact:
                self._action(lead, "SCHEDULE_NURTURE_FOLLOW_UP", "SIMULATED", {"next_step": "collect_missing_criteria"})
        self._record(lead, "LEAD_PROCESSING_COMPLETED", {"state": lead.state, "score": lead.score})
        return {"lead_id": lead.lead_id, "organization_id": lead.organization_id,
                "state": lead.state, "score": lead.score,
                "actions_added": len(lead.actions) - start_actions,
                "actions": list(lead.actions), "audit": list(lead.audit),
                "simulation_only": True, "external_side_effects": 0}


def lead_from_dict(data: dict[str, Any]) -> RealEstateLead:
    allowed = set(RealEstateLead.__dataclass_fields__) - {"actions", "audit", "idempotency_keys", "score", "state"}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError("Unknown lead fields: " + ", ".join(sorted(unknown)))
    return RealEstateLead(**data)
