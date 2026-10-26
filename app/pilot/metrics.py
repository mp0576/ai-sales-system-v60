"""Small, provider-neutral pilot KPI calculation helpers."""
from __future__ import annotations
from collections import Counter
from typing import Iterable, Mapping

FUNNEL = (
    "LEAD_IMPORTED", "FIRST_RESPONSE_SENT", "LEAD_QUALIFIED", "VISIT_BOOKED",
    "PROPOSAL_SENT", "PAYMENT_RECEIVED", "CUSTOMER_ACTIVE",
)


def calculate_pilot_metrics(events: Iterable[Mapping]) -> dict:
    counts = Counter(str(event.get("type", "")) for event in events)
    imported = counts["LEAD_IMPORTED"]
    contacted = counts["FIRST_RESPONSE_SENT"]
    qualified = counts["LEAD_QUALIFIED"]
    booked = counts["VISIT_BOOKED"]
    return {
        "funnel_counts": {stage: counts[stage] for stage in FUNNEL},
        "response_rate": round(contacted / imported, 4) if imported else 0.0,
        "qualification_rate_from_contacted": round(qualified / contacted, 4) if contacted else 0.0,
        "booking_rate_from_qualified": round(booked / qualified, 4) if qualified else 0.0,
        "human_intervention_rate": round(counts["HUMAN_INTERVENTION"] / imported, 4) if imported else 0.0,
        "provider_unknown_outcomes": counts["PROVIDER_OUTCOME_UNKNOWN"],
        "failed_actions": counts["ACTION_FAILED"],
        "duplicate_suppressed": counts["DUPLICATE_SUPPRESSED"],
    }
