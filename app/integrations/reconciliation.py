"""Decision policy for ambiguous provider outcomes.

Never infer failure from a timeout: the provider may have accepted the request.
This module deliberately does not perform provider lookups or retries itself; a
provider-specific reconciler must supply authoritative evidence first.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .base import ProviderResult


class Outcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    DEFINITIVE_FAILURE = "DEFINITIVE_FAILURE"
    UNKNOWN = "UNKNOWN"


class NextStep(str, Enum):
    COMPLETE = "COMPLETE"
    MARK_FAILED = "MARK_FAILED"
    LOOKUP_PROVIDER = "LOOKUP_PROVIDER"
    RETRY_SAME_KEY = "RETRY_SAME_KEY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class ReconciliationDecision:
    outcome: Outcome
    next_step: NextStep
    reason: str


def classify_provider_result(result: ProviderResult) -> ReconciliationDecision:
    """Classify only evidence represented in a normalized provider result."""
    status = (result.status or "UNKNOWN").strip().upper()
    if result.ok and result.external_id:
        return ReconciliationDecision(Outcome.CONFIRMED, NextStep.COMPLETE,
                                      "Provider returned success and an external identifier")
    if not result.ok and not result.retryable and status in {
        "DECLINED", "REJECTED", "INVALID", "FAILED", "CANCELED", "CANCELLED"
    }:
        return ReconciliationDecision(Outcome.DEFINITIVE_FAILURE, NextStep.MARK_FAILED,
                                      "Provider returned an explicit definitive failure")
    return ReconciliationDecision(Outcome.UNKNOWN, NextStep.LOOKUP_PROVIDER,
                                  "Result does not prove success or definitive failure")


def classify_transport_exception(*, provider_supports_idempotency: bool,
                                 provider_lookup_available: bool) -> ReconciliationDecision:
    """Timeouts and transport errors are ambiguous, not definitive failures."""
    if provider_lookup_available:
        return ReconciliationDecision(Outcome.UNKNOWN, NextStep.LOOKUP_PROVIDER,
                                      "Check provider state using the original idempotency key")
    if provider_supports_idempotency:
        return ReconciliationDecision(Outcome.UNKNOWN, NextStep.RETRY_SAME_KEY,
                                      "Retry only with the exact original idempotency key")
    return ReconciliationDecision(Outcome.UNKNOWN, NextStep.MANUAL_REVIEW,
                                  "No safe automated recovery path is available")


def require_same_idempotency_key(original: str, retry: str) -> None:
    """Fail closed if a recovery attempt could create a second external side effect."""
    if not original or not retry:
        raise ValueError("original and retry idempotency keys are required")
    if original != retry:
        raise ValueError("ambiguous outcomes must be reconciled with the original idempotency key")
