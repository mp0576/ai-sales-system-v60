from pathlib import Path
import pytest
from app.integrations.base import CheckoutRequest, OutboundMessage, ProviderResult
from app.integrations.gateway import ActionBlocked, ActionContext, InternalActionGateway
from app.integrations.mock import MockPaymentProvider


def test_retryable_provider_result_is_not_cached():
    class Provider:
        calls = 0
        def send(self, message, *, subject):
            self.calls += 1
            if self.calls == 1:
                return ProviderResult(False, "email", status="RETRY", retryable=True, error="temporary")
            return ProviderResult(True, "email", external_id="msg-1", status="ACCEPTED")
    provider = Provider()
    gateway = InternalActionGateway(email=provider)
    ctx = ActionContext("org-a", outbound_enabled=True)
    msg = OutboundMessage("org-a", "user@example.test", "hello", "stable-key")
    assert gateway.send_email(ctx, msg, subject="Test").retryable
    assert gateway.send_email(ctx, msg, subject="Test").ok
    assert gateway.send_email(ctx, msg, subject="Test").ok
    assert provider.calls == 2


def test_checkout_requires_explicit_payment_feature_flag():
    gateway = InternalActionGateway(payments=MockPaymentProvider())
    request = CheckoutRequest("org-a", "proposal-a", 1000, "EUR", "https://example.test/s", "https://example.test/c", "checkout-a")
    with pytest.raises(ActionBlocked, match="Payment actions are disabled"):
        gateway.create_checkout(ActionContext("org-a"), request)


def test_checkout_flag_does_not_bypass_approval_or_tenant_guard():
    gateway = InternalActionGateway(payments=MockPaymentProvider())
    request = CheckoutRequest("org-a", "proposal-a", 1000, "EUR", "https://example.test/s", "https://example.test/c", "checkout-b")
    with pytest.raises(ActionBlocked, match="Human approval required"):
        gateway.create_checkout(ActionContext("org-a", payments_enabled=True, requires_approval=True), request)
    with pytest.raises(ActionBlocked, match="Tenant mismatch"):
        gateway.create_checkout(ActionContext("org-b", payments_enabled=True), request)


def test_v21_project_state_documents_hardening():
    text = Path("PROJECT_STATE.md").read_text(encoding="utf-8")
    assert "MVP v21" in text
    assert "payments_enabled" in text
    assert "retryable" in text
