"""Policy-first gateway for outbound side effects."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .base import OutboundMessage, CalendarBooking, CheckoutRequest, ProviderResult

@dataclass(frozen=True)
class ActionContext:
    organization_id: str
    automation_enabled: bool = True
    outbound_enabled: bool = False
    payments_enabled: bool = False
    do_not_contact: bool = False
    requires_approval: bool = False
    approved: bool = False

class ActionBlocked(PermissionError): pass

class InternalActionGateway:
    def __init__(self, *, messaging=None, calendar=None, payments=None, email=None, idempotency_store=None, worker_id="action-gateway"):
        self.messaging=messaging; self.calendar=calendar; self.payments=payments; self.email=email; self._results={}
        self.idempotency_store=idempotency_store; self.worker_id=worker_id
    def _authorize(self, ctx: ActionContext, org: str, *, outbound=False, payments=False):
        if not ctx.organization_id or ctx.organization_id != org: raise ActionBlocked("Tenant mismatch")
        if not ctx.automation_enabled: raise ActionBlocked("Automation kill switch is enabled")
        if outbound and ctx.do_not_contact: raise ActionBlocked("Contact is on the do-not-contact list")
        if outbound and not ctx.outbound_enabled: raise ActionBlocked("Outbound messaging is disabled for this organization")
        if payments and not ctx.payments_enabled: raise ActionBlocked("Payment actions are disabled for this organization")
        if ctx.requires_approval and not ctx.approved: raise ActionBlocked("Human approval required")
    def _once(self, key: str, call, *, organization_id: str, action_type: str) -> ProviderResult:
        if not key: raise ValueError("idempotency key is required")
        # The durable store arbitrates duplicate work across independent API/worker processes.
        # Provider calls remain outside database transactions; the provider must also honor the
        # stable idempotency key because a timeout can leave the external outcome ambiguous.
        if self.idempotency_store is not None:
            return self.idempotency_store.execute_once(
                organization_id=organization_id, action_type=action_type,
                idempotency_key=key, worker_id=self.worker_id, call=call,
            )
        local_key=f"{organization_id}:{action_type}:{key}"
        if local_key in self._results: return self._results[local_key]
        result=call()
        # Process-local fallback is suitable only for tests/development, never multi-worker production.
        if result.ok or not result.retryable:
            self._results[local_key]=result
        return result
    def send_message(self, ctx: ActionContext, message: OutboundMessage) -> ProviderResult:
        self._authorize(ctx,message.organization_id,outbound=True)
        if not self.messaging: return ProviderResult(False,"none",status="BLOCKED",error="Messaging provider not configured")
        return self._once(message.idempotency_key,lambda:self.messaging.send(message),organization_id=message.organization_id,action_type="message")
    def send_email(self, ctx: ActionContext, message: OutboundMessage, *, subject: str) -> ProviderResult:
        self._authorize(ctx,message.organization_id,outbound=True)
        if not self.email: return ProviderResult(False,"none",status="BLOCKED",error="Email provider not configured")
        return self._once(message.idempotency_key,lambda:self.email.send(message,subject=subject),organization_id=message.organization_id,action_type="email")
    def book_meeting(self, ctx: ActionContext, booking: CalendarBooking) -> ProviderResult:
        self._authorize(ctx,booking.organization_id)
        if not self.calendar: return ProviderResult(False,"none",status="BLOCKED",error="Calendar provider not configured")
        return self._once(booking.idempotency_key,lambda:self.calendar.book(booking),organization_id=booking.organization_id,action_type="calendar")
    def create_checkout(self, ctx: ActionContext, request: CheckoutRequest) -> ProviderResult:
        self._authorize(ctx,request.organization_id,payments=True)
        if not self.payments: return ProviderResult(False,"none",status="BLOCKED",error="Payment provider not configured")
        return self._once(request.idempotency_key,lambda:self.payments.create_checkout(request),organization_id=request.organization_id,action_type="checkout")
