"""Deterministic providers for local development and tests; never charge/send externally."""
from __future__ import annotations
from .base import ProviderResult, OutboundMessage, CalendarBooking, CheckoutRequest

class MockMessagingProvider:
    def __init__(self, name: str = "mock-messaging"):
        self.name=name; self.sent={}
    def send(self, message: OutboundMessage) -> ProviderResult:
        if message.idempotency_key in self.sent: return self.sent[message.idempotency_key]
        result=ProviderResult(True,self.name,f"msg_{len(self.sent)+1}","SENT",{"to":message.to})
        self.sent[message.idempotency_key]=result; return result

class MockCalendarProvider:
    def __init__(self): self.bookings={}
    def book(self, booking: CalendarBooking) -> ProviderResult:
        if booking.idempotency_key in self.bookings: return self.bookings[booking.idempotency_key]
        result=ProviderResult(True,"mock-calendar",f"event_{len(self.bookings)+1}","BOOKED",{"start":booking.start_iso,"end":booking.end_iso})
        self.bookings[booking.idempotency_key]=result; return result

class MockPaymentProvider:
    def __init__(self): self.sessions={}
    def create_checkout(self, request: CheckoutRequest) -> ProviderResult:
        if request.idempotency_key in self.sessions: return self.sessions[request.idempotency_key]
        result=ProviderResult(True,"mock-payment",f"cs_{len(self.sessions)+1}","CHECKOUT_CREATED",{"url":"https://example.invalid/mock-checkout","amount_minor":request.amount_minor,"currency":request.currency.lower()})
        self.sessions[request.idempotency_key]=result; return result

class MockEmailProvider(MockMessagingProvider):
    def __init__(self): super().__init__("mock-email"); self.subjects={}
    def send(self, message: OutboundMessage, *, subject: str) -> ProviderResult:
        result=super().send(message); self.subjects[message.idempotency_key]=subject; return result
