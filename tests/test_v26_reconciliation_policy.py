import pytest
from app.integrations.base import ProviderResult
from app.integrations.reconciliation import (
    Outcome, NextStep, classify_provider_result, classify_transport_exception,
    require_same_idempotency_key,
)


def test_success_with_external_id_is_confirmed():
    d = classify_provider_result(ProviderResult(True, "stripe", "cs_123", "CREATED"))
    assert (d.outcome, d.next_step) == (Outcome.CONFIRMED, NextStep.COMPLETE)

@pytest.mark.parametrize("status", ["DECLINED", "REJECTED", "INVALID", "FAILED", "CANCELED", "CANCELLED"])
def test_explicit_definitive_failure_is_not_retried(status):
    d = classify_provider_result(ProviderResult(False, "stripe", status=status, retryable=False))
    assert (d.outcome, d.next_step) == (Outcome.DEFINITIVE_FAILURE, NextStep.MARK_FAILED)

@pytest.mark.parametrize("result", [
    ProviderResult(False, "stripe", status="UNKNOWN", retryable=True),
    ProviderResult(False, "stripe", status="TIMEOUT", retryable=False),
    ProviderResult(True, "stripe", status="CREATED", external_id=None),
])
def test_incomplete_evidence_requires_lookup(result):
    d = classify_provider_result(result)
    assert (d.outcome, d.next_step) == (Outcome.UNKNOWN, NextStep.LOOKUP_PROVIDER)

def test_timeout_prefers_authoritative_provider_lookup():
    d = classify_transport_exception(provider_supports_idempotency=True, provider_lookup_available=True)
    assert d.next_step == NextStep.LOOKUP_PROVIDER

def test_timeout_can_retry_only_same_key_when_provider_idempotent():
    d = classify_transport_exception(provider_supports_idempotency=True, provider_lookup_available=False)
    assert d.next_step == NextStep.RETRY_SAME_KEY
    require_same_idempotency_key("org:checkout:proposal-1", "org:checkout:proposal-1")

def test_timeout_without_safe_recovery_requires_manual_review():
    d = classify_transport_exception(provider_supports_idempotency=False, provider_lookup_available=False)
    assert (d.outcome, d.next_step) == (Outcome.UNKNOWN, NextStep.MANUAL_REVIEW)

def test_new_key_for_ambiguous_retry_is_rejected():
    with pytest.raises(ValueError, match="original idempotency key"):
        require_same_idempotency_key("original", "fresh-key")

@pytest.mark.parametrize("keys", [("", "x"), ("x", "")])
def test_missing_idempotency_key_is_rejected(keys):
    with pytest.raises(ValueError):
        require_same_idempotency_key(*keys)
