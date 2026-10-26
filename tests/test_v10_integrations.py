import hashlib, hmac, json
import pytest
from app.integrations.base import OutboundMessage, CalendarBooking, CheckoutRequest, ProviderResult
from app.integrations.gateway import ActionContext, ActionBlocked, InternalActionGateway
from app.integrations.mock import MockMessagingProvider, MockCalendarProvider, MockPaymentProvider, MockEmailProvider
from app.integrations.http import WhatsAppCloudAdapter, StripeCheckoutAdapter, GoogleCalendarAdapter, verify_stripe_signature


def ctx(**kw): return ActionContext(organization_id="org_1", **kw)

def test_outbound_disabled_by_default_and_tenant_guard():
    gateway=InternalActionGateway(messaging=MockMessagingProvider())
    msg=OutboundMessage("org_1","+351900000000","Olá","key1")
    with pytest.raises(ActionBlocked): gateway.send_message(ctx(),msg)
    with pytest.raises(ActionBlocked): gateway.send_message(ActionContext("org_2",outbound_enabled=True),msg)

def test_dnc_and_approval_block_before_provider_call():
    p=MockMessagingProvider(); gateway=InternalActionGateway(messaging=p)
    msg=OutboundMessage("org_1","+351900000000","Olá","key1")
    with pytest.raises(ActionBlocked): gateway.send_message(ctx(outbound_enabled=True,do_not_contact=True),msg)
    with pytest.raises(ActionBlocked): gateway.send_message(ctx(outbound_enabled=True,requires_approval=True),msg)
    assert p.sent == {}

def test_gateway_idempotency_prevents_duplicate_external_call():
    p=MockMessagingProvider(); gateway=InternalActionGateway(messaging=p)
    msg=OutboundMessage("org_1","+351900000000","Olá","key1")
    a=gateway.send_message(ctx(outbound_enabled=True),msg); b=gateway.send_message(ctx(outbound_enabled=True),msg)
    assert a == b and len(p.sent)==1

def test_calendar_and_checkout_tenant_safe_idempotency():
    cal=MockCalendarProvider(); pay=MockPaymentProvider(); gateway=InternalActionGateway(calendar=cal,payments=pay)
    booking=CalendarBooking("org_1","primary","Demo","2026-10-12T10:00:00+01:00","2026-10-12T10:30:00+01:00","Europe/Lisbon",("a@example.com",),"book1")
    assert gateway.book_meeting(ctx(),booking)==gateway.book_meeting(ctx(),booking)
    checkout=CheckoutRequest("org_1","prop1",49900,"EUR","https://example.com/success","https://example.com/cancel","pay1")
    assert gateway.create_checkout(ctx(payments_enabled=True),checkout)==gateway.create_checkout(ctx(payments_enabled=True),checkout)
    assert len(cal.bookings)==1 and len(pay.sessions)==1

def test_missing_provider_returns_blocked_not_fake_success():
    result=InternalActionGateway().create_checkout(ctx(payments_enabled=True),CheckoutRequest("org_1","p1",49900,"EUR","https://a.test","https://b.test","k"))
    assert not result.ok and result.status=="BLOCKED"

def test_whatsapp_adapter_maps_success_and_idempotency_header():
    calls=[]
    def transport(method,url,headers,body,timeout):
        calls.append((method,url,headers,body,timeout)); return 200,{"messages":[{"id":"wamid.1"}],"id":"wamid.1"}
    adapter=WhatsAppCloudAdapter(phone_number_id="phone",access_token="token",transport=transport)
    r=adapter.send(OutboundMessage("org_1","+351900000000","Olá","msg-1"))
    assert r.ok and r.provider=="whatsapp" and calls[0][2]["Idempotency-Key"]=="msg-1"
    assert calls[0][3]["messaging_product"]=="whatsapp"

def test_provider_errors_are_classified_for_retry():
    adapter=WhatsAppCloudAdapter(phone_number_id="p",access_token="t",transport=lambda *a:(503,{"error":"down"}))
    result=adapter.send(OutboundMessage("org_1","+351900000000","Olá","k"))
    assert not result.ok and result.retryable
    adapter2=WhatsAppCloudAdapter(phone_number_id="p",access_token="t",transport=lambda *a:(400,{"error":"bad request"}))
    result2=adapter2.send(OutboundMessage("org_1","+351900000000","Olá","k2"))
    assert not result2.ok and not result2.retryable

def test_missing_credentials_are_blocked():
    result=WhatsAppCloudAdapter(phone_number_id="p",access_token="").send(OutboundMessage("org_1","+351900000000","Olá","k"))
    assert not result.ok and result.status=="BLOCKED"

def test_stripe_webhook_signature_and_timestamp_tolerance():
    payload=json.dumps({"id":"evt_1"},separators=(",",":")).encode(); secret="whsec_test"; ts=1000
    digest=hmac.new(secret.encode(),str(ts).encode()+b"."+payload,hashlib.sha256).hexdigest()
    header=f"t={ts},v1={digest}"
    assert verify_stripe_signature(payload,header,secret,now=1000)
    assert not verify_stripe_signature(payload,header,"wrong",now=1000)
    assert not verify_stripe_signature(payload,header,secret,now=2000)

def test_stripe_checkout_validates_amount_and_uses_provider_idempotency():
    calls=[]
    def transport(method,url,headers,body,timeout):
        calls.append((method,url,headers,body)); return 200,{"id":"cs_123","url":"https://checkout.stripe.test/session"}
    adapter=StripeCheckoutAdapter(secret_key="sk_test",transport=transport)
    req=CheckoutRequest("org_1","prop_1",49900,"EUR","https://a.test/s","https://a.test/c","checkout-1")
    result=adapter.create_checkout(req)
    assert result.ok and result.external_id=="cs_123"
    assert calls[0][2]["Idempotency-Key"]=="checkout-1"
    bad=adapter.create_checkout(CheckoutRequest("org_1","p",0,"EUR","https://a.test/s","https://a.test/c","k"))
    assert not bad.ok and bad.status=="BLOCKED"

def test_calendar_adapter_sends_timezone_and_attendees():
    calls=[]
    adapter=GoogleCalendarAdapter(access_token="token",transport=lambda *args:(calls.append(args) or (200,{"id":"event_1","htmlLink":"https://calendar.test/event"})))
    b=CalendarBooking("org_1","primary","Demo","2026-10-12T10:00:00+01:00","2026-10-12T10:30:00+01:00","Europe/Lisbon",("a@example.com",),"cal-1")
    result=adapter.book(b)
    assert result.ok and result.external_id=="event_1"
    assert calls[0][3]["start"]["timeZone"]=="Europe/Lisbon"
    assert calls[0][3]["attendees"]==[{"email":"a@example.com"}]

def test_transient_provider_failure_is_not_cached_and_can_recover():
    class FlakyProvider:
        def __init__(self): self.calls = 0
        def send(self, message):
            self.calls += 1
            if self.calls == 1:
                return ProviderResult(False, "whatsapp", status="RETRY", retryable=True, error="temporary")
            return ProviderResult(True, "whatsapp", external_id="wamid.recovered", status="ACCEPTED")
    provider = FlakyProvider()
    gateway = InternalActionGateway(messaging=provider)
    message = OutboundMessage("org_1", "+351900000000", "Olá", "retry-key")
    context = ctx(outbound_enabled=True)
    first = gateway.send_message(context, message)
    second = gateway.send_message(context, message)
    third = gateway.send_message(context, message)
    assert not first.ok and first.retryable
    assert second.ok and third == second
    assert provider.calls == 2


def test_payment_actions_are_disabled_by_default_and_require_explicit_enablement():
    provider = MockPaymentProvider()
    gateway = InternalActionGateway(payments=provider)
    request = CheckoutRequest("org_1", "prop1", 49900, "EUR", "https://a.test/s", "https://a.test/c", "pay-safe")
    with pytest.raises(ActionBlocked, match="Payment actions are disabled"):
        gateway.create_checkout(ctx(), request)
    assert provider.sessions == {}
    result = gateway.create_checkout(ctx(payments_enabled=True), request)
    assert result.ok
    assert len(provider.sessions) == 1


def test_payment_action_requires_approval_even_when_enabled():
    gateway = InternalActionGateway(payments=MockPaymentProvider())
    request = CheckoutRequest("org_1", "prop2", 49900, "EUR", "https://a.test/s", "https://a.test/c", "pay-approval")
    with pytest.raises(ActionBlocked, match="Human approval required"):
        gateway.create_checkout(ctx(payments_enabled=True, requires_approval=True), request)
