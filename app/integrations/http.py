"""Minimal HTTP adapters with injected transport, safe to test without network.
A production deployment should inject a timeout-configured HTTP client, secret
manager-backed tokens, and provider-specific webhook verification.
"""
from __future__ import annotations
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from .base import ProviderResult, OutboundMessage, CalendarBooking, CheckoutRequest

Transport = Callable[[str, str, dict[str,str], dict[str,Any], float], tuple[int,dict[str,Any]]]
def urllib_transport(method: str, url: str, headers: dict[str,str], body: dict[str,Any], timeout: float):
    req=Request(url,data=json.dumps(body).encode() if method.upper()!="GET" else None,headers={**headers,"Content-Type":"application/json"},method=method.upper())
    try:
        with urlopen(req,timeout=timeout) as response:
            raw=response.read().decode(); return response.status,(json.loads(raw) if raw else {})
    except HTTPError as e:
        raw=e.read().decode(errors="replace")
        try: payload=json.loads(raw)
        except Exception: payload={"message":raw[:500]}
        return e.code,payload
    except URLError as e:
        raise ConnectionError(str(e)) from e

def stripe_form_transport(method: str, url: str, headers: dict[str,str], body: dict[str,Any], timeout: float):
    """Stripe-specific form transport (Stripe API expects URL-encoded fields)."""
    req=Request(url,data=urlencode(body).encode(),headers={**headers,"Content-Type":"application/x-www-form-urlencoded"},method=method.upper())
    try:
        with urlopen(req,timeout=timeout) as response:
            raw=response.read().decode(); return response.status,(json.loads(raw) if raw else {})
    except HTTPError as e:
        raw=e.read().decode(errors="replace")
        try: payload=json.loads(raw)
        except Exception: payload={"message":raw[:500]}
        return e.code,payload
    except URLError as e:
        raise ConnectionError(str(e)) from e

def _call(transport, provider, method, url, token, body, key, timeout):
    if not token: return ProviderResult(False,provider,status="BLOCKED",error="Missing provider credential")
    try: status,payload=transport(method,url,{"Authorization":f"Bearer {token}","Idempotency-Key":key},body,timeout)
    except (ConnectionError,TimeoutError) as e: return ProviderResult(False,provider,status="RETRY",retryable=True,error=str(e))
    except Exception as e: return ProviderResult(False,provider,status="ERROR",retryable=False,error=f"Transport error: {type(e).__name__}")
    if 200 <= status < 300:
        ext=str(payload.get("id") or payload.get("message_id") or "") or None
        return ProviderResult(True,provider,ext,"ACCEPTED",payload)
    retryable=status==429 or status>=500
    return ProviderResult(False,provider,status="RETRY" if retryable else "REJECTED",data=payload,retryable=retryable,error=f"HTTP {status}")

class WhatsAppCloudAdapter:
    def __init__(self, *, phone_number_id: str, access_token: str, graph_version: str="v21.0", transport=urllib_transport, timeout: float=10):
        self.phone_number_id=phone_number_id; self.access_token=access_token; self.transport=transport; self.timeout=timeout; self.graph_version=graph_version
    def send(self, message: OutboundMessage) -> ProviderResult:
        body={"messaging_product":"whatsapp","recipient_type":"individual","to":message.to,"type":"text","text":{"preview_url":False,"body":message.text}}
        return _call(self.transport,"whatsapp", "POST",f"https://graph.facebook.com/{self.graph_version}/{self.phone_number_id}/messages",self.access_token,body,message.idempotency_key,self.timeout)

class StripeCheckoutAdapter:
    """Creates a Checkout Session. Payment completion MUST be confirmed by a signed webhook."""
    def __init__(self, *, secret_key: str, transport=stripe_form_transport, timeout: float=10, api_base: str="https://api.stripe.com/v1"):
        self.secret_key=secret_key; self.transport=transport; self.timeout=timeout; self.api_base=api_base.rstrip("/")
    def create_checkout(self, request: CheckoutRequest) -> ProviderResult:
        if request.amount_minor <= 0 or len(request.currency)!=3: return ProviderResult(False,"stripe",status="BLOCKED",error="Invalid amount or currency")
        # Stripe's API is form-encoded; injected transport contract accepts JSON for tests.
        body={"mode":"payment","success_url":request.success_url,"cancel_url":request.cancel_url,
              "client_reference_id":request.proposal_id,"metadata[organization_id]":request.organization_id,
              "metadata[proposal_id]":request.proposal_id,"line_items[0][quantity]":"1",
              "line_items[0][price_data][currency]":request.currency.lower(),
              "line_items[0][price_data][unit_amount]":str(request.amount_minor),
              "line_items[0][price_data][product_data][name]":f"Proposal {request.proposal_id}"}
        return _call(self.transport,"stripe","POST",f"{self.api_base}/checkout/sessions",self.secret_key,body,request.idempotency_key,self.timeout)

class GoogleCalendarAdapter:
    def __init__(self, *, access_token: str, transport=urllib_transport, timeout: float=10): self.access_token=access_token; self.transport=transport; self.timeout=timeout
    def book(self, booking: CalendarBooking) -> ProviderResult:
        body={"summary":booking.title,"start":{"dateTime":booking.start_iso,"timeZone":booking.timezone},"end":{"dateTime":booking.end_iso,"timeZone":booking.timezone},"attendees":[{"email":e} for e in booking.attendees],"extendedProperties":{"private":{"organization_id":booking.organization_id,"idempotency_key":booking.idempotency_key}}}
        return _call(self.transport,"google-calendar","POST",f"https://www.googleapis.com/calendar/v3/calendars/{booking.calendar_id}/events",self.access_token,body,booking.idempotency_key,self.timeout)

def verify_stripe_signature(payload: bytes, signature_header: str, secret: str, *, tolerance_seconds: int=300, now: int | None=None) -> bool:
    """Verify Stripe-Signature v1 using constant-time HMAC comparison."""
    import hashlib, hmac, time
    if not payload or not signature_header or not secret: return False
    parts={}
    for item in signature_header.split(","):
        if "=" in item:
            k,v=item.split("=",1); parts.setdefault(k,[]).append(v)
    try: timestamp=int(parts["t"][0]); signatures=parts.get("v1",[])
    except (KeyError,ValueError,IndexError): return False
    current=int(time.time()) if now is None else int(now)
    if abs(current-timestamp)>tolerance_seconds: return False
    signed=str(timestamp).encode()+b"."+payload
    expected=hmac.new(secret.encode(),signed,hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected,s) for s in signatures)


class ResendEmailAdapter:
    """Transactional email adapter using the Resend REST API."""
    def __init__(self, *, api_key: str, from_email: str, transport=urllib_transport, timeout: float=10):
        self.api_key=api_key; self.from_email=from_email; self.transport=transport; self.timeout=timeout
    def send(self, message: OutboundMessage, *, subject: str) -> ProviderResult:
        body={"from":self.from_email,"to":[message.to],"subject":subject,"text":message.text}
        return _call(self.transport,"resend-email","POST","https://api.resend.com/emails",self.api_key,body,message.idempotency_key,self.timeout)
