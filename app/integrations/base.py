"""Provider-neutral contracts for external side effects.

All provider calls are made outside database transactions. Implementations must
return provider IDs and must not treat an HTTP 2xx alone as proof of payment.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol

@dataclass(frozen=True)
class ProviderResult:
    ok: bool
    provider: str
    external_id: str | None = None
    status: str = "UNKNOWN"
    data: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    error: str | None = None

@dataclass(frozen=True)
class OutboundMessage:
    organization_id: str
    to: str
    text: str
    idempotency_key: str

@dataclass(frozen=True)
class CalendarBooking:
    organization_id: str
    calendar_id: str
    title: str
    start_iso: str
    end_iso: str
    timezone: str
    attendees: tuple[str, ...] = ()
    idempotency_key: str = ""

@dataclass(frozen=True)
class CheckoutRequest:
    organization_id: str
    proposal_id: str
    amount_minor: int
    currency: str
    success_url: str
    cancel_url: str
    idempotency_key: str

class MessagingProvider(Protocol):
    def send(self, message: OutboundMessage) -> ProviderResult: ...
class CalendarProvider(Protocol):
    def book(self, booking: CalendarBooking) -> ProviderResult: ...
class PaymentProvider(Protocol):
    def create_checkout(self, request: CheckoutRequest) -> ProviderResult: ...
class EmailProvider(Protocol):
    def send(self, message: OutboundMessage, *, subject: str) -> ProviderResult: ...
