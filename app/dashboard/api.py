"""Authenticated dashboard API. Demo repository is in-memory; production uses RLS-backed repositories."""
from __future__ import annotations
import os
import hmac
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field
from app.dashboard.supabase_store import (SupabaseDashboardRepository, Principal, AuthenticationError, TenantAccessError, RepositoryError)
from app.repositories.real_estate_leads import SQLiteLeadRepository, LeadConflict
from app.dashboard.supabase_leads import SupabaseLeadRepository
from app.services.public_demo_requests import PublicDemoRequestRepository, IntakeError

class LeadUpsert(BaseModel):
    lead_id: str = Field(min_length=1, max_length=250)
    state: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=0)

class PublicDemoRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    company: str = Field(min_length=2, max_length=160)
    phone: str = Field(default="", max_length=40)
    team_size: str
    monthly_leads: str
    notes: str = Field(default="", max_length=2000)
    consent: bool
    website: str = Field(default="", max_length=500)


class DemoRequestStatus(BaseModel):
    status: Literal["NEW", "CONTACTED", "QUALIFIED", "WON", "LOST"]


class ApprovalResolution(BaseModel):
    approved: bool
    reason: str = Field(min_length=3, max_length=1000)

@dataclass
class ApprovalItem:
    id: str
    organization_id: str
    action_type: str
    summary: str
    risk_level: str
    status: str = "PENDING"
    requested_at: str = "2026-10-09T08:00:00+00:00"
    resolved_at: str | None = None
    resolution_reason: str | None = None

class DashboardStore:
    """Replaceable repository; never treat this demo store as durable production state."""
    def __init__(self):
        self.approvals: dict[str, ApprovalItem] = {
            "apr_demo_001": ApprovalItem("apr_demo_001", "org_demo", "DISCOUNT_OVERRIDE", "Requested discount above the autonomous limit", "HIGH"),
            "apr_demo_002": ApprovalItem("apr_demo_002", "org_demo", "CUSTOM_CONTRACT", "Review a non-standard contract clause", "CRITICAL"),
        }
        self.metrics = {"leads_total": 128, "qualified": 37, "customers_active": 12, "human_intervention_rate": 0.14, "ai_cost_month_eur": 42.80, "automation_success_rate": 0.972}
        self.executions = [
            {"id":"exe_demo_003","organization_id":"org_demo","workflow":"Lead qualification","status":"SUCCEEDED","duration_ms":842,"created_at":"2026-10-09T08:40:00+00:00"},
            {"id":"exe_demo_002","organization_id":"org_demo","workflow":"Follow-up scheduler","status":"RETRYING","duration_ms":1200,"created_at":"2026-10-09T08:35:00+00:00"},
            {"id":"exe_demo_001","organization_id":"org_demo","workflow":"Payment webhook","status":"FAILED","duration_ms":97,"created_at":"2026-10-09T08:31:00+00:00"},
        ]
        self.events = [{"type":"APPROVAL_REQUIRED","count":2},{"type":"AUTOMATION_FAILED","count":1},{"type":"FOLLOW_UP_SENT","count":46}]

    def tenant_approvals(self, org: str):
        return [asdict(a) for a in self.approvals.values() if a.organization_id == org]
    def resolve(self, org: str, approval_id: str, approved: bool, reason: str):
        item = self.approvals.get(approval_id)
        if not item or item.organization_id != org:
            raise KeyError("approval not found")
        if item.status != "PENDING":
            raise RuntimeError("approval already resolved")
        item.status = "APPROVED" if approved else "REJECTED"
        item.resolved_at = datetime.now(timezone.utc).isoformat()
        item.resolution_reason = reason
        return asdict(item)

store = DashboardStore()
app = FastAPI(title="AI Sales System Dashboard API", version="60.0.0")
_supabase_repository = None
def supabase_repository():
    global _supabase_repository
    if _supabase_repository is None:
        _supabase_repository = SupabaseDashboardRepository()
    return _supabase_repository
_STATIC_DIR = Path(__file__).resolve().parents[2] / "dashboard"
app.mount("/dashboard", StaticFiles(directory=str(_STATIC_DIR)), name="dashboard-assets")

_lead_repository = None
def lead_repository(principal: Principal | None = None):
    """Use caller-JWT/RLS storage in production and SQLite only in local pilot."""
    global _lead_repository
    if os.getenv("APP_ENV", "pilot").lower() == "production":
        if principal is None:
            raise RepositoryError("Authenticated Supabase principal required; refusing SQLite fallback")
        return SupabaseLeadRepository(principal.access_token)
    if _lead_repository is None:
        db_path = os.getenv("LEAD_DATABASE_PATH", "data/real_estate_leads.sqlite3")
        _lead_repository = SQLiteLeadRepository(db_path)
    return _lead_repository


def require_dashboard_access(organization_id: str, authorization: str | None = Header(default=None)):
    """Production mode requires a real Supabase user and verified tenant membership.

    The static bearer token is deliberately available only in local/demo mode.
    """
    if os.getenv("APP_ENV", "pilot").lower() == "production":
        try:
            return supabase_repository().authenticate(authorization, organization_id)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        except TenantAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    expected = os.getenv("DASHBOARD_API_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Dashboard API disabled: configure DASHBOARD_API_TOKEN")
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return None



_public_intake_repository = None
def public_intake_repository():
    global _public_intake_repository
    if _public_intake_repository is None:
        _public_intake_repository = PublicDemoRequestRepository()
    return _public_intake_repository


def require_intake_admin(authorization: str | None = Header(default=None)):
    expected = os.getenv("PUBLIC_INTAKE_ADMIN_TOKEN", "")
    if len(expected) < 24:
        raise HTTPException(status_code=503, detail="Public intake admin disabled: configure PUBLIC_INTAKE_ADMIN_TOKEN (24+ characters)")
    supplied = authorization or ""
    if not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="Invalid intake admin token")
    return True


@app.get("/offer", response_class=HTMLResponse)
def commercial_offer():
    offer_path = _STATIC_DIR / "offer.html"
    return FileResponse(str(offer_path), media_type="text/html")


@app.post("/api/v1/public/demo-requests", status_code=201)
def create_public_demo_request(body: PublicDemoRequest,
                               idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=250)):
    try:
        item, replayed = public_intake_repository().create(body.model_dump(), idempotency_key)
        return {"request_id": item["id"], "status": item["status"], "created_at": item["created_at"],
                "replayed": replayed, "message": "Pedido recebido. A equipa irá analisar o pedido."}
    except IntakeError as exc:
        status = 429 if "Too many requests" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc))


@app.get("/api/v1/admin/demo-requests")
def list_public_demo_requests(status: Literal["NEW", "CONTACTED", "QUALIFIED", "WON", "LOST", "ALL"] = "ALL",
                              limit: int = 100, _admin: bool = Depends(require_intake_admin)):
    try:
        items = public_intake_repository().list_requests(status=status, limit=limit)
        return {"items": items, "count": len(items), "data_mode": "LOCAL_DURABLE_INTAKE"}
    except IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.patch("/api/v1/admin/demo-requests/{request_id}")
def update_public_demo_request(request_id: str, body: DemoRequestStatus,
                               _admin: bool = Depends(require_intake_admin)):
    try:
        return public_intake_repository().update_status(request_id, body.status)
    except KeyError:
        raise HTTPException(status_code=404, detail="Demo request not found")
    except IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/health")
def health():
    return {"status":"ok", "component":"dashboard-api", "mode":"supabase-auth-and-rls" if os.getenv("APP_ENV", "pilot").lower() == "production" else "demo-store-not-production"}

@app.get("/api/v1/organizations/{organization_id}/overview")
def overview(organization_id: str, principal: Principal | None = Depends(require_dashboard_access)):
    if principal is not None:
        try: return supabase_repository().overview(principal)
        except TenantAccessError as exc: raise HTTPException(status_code=403, detail=str(exc))
        except AuthenticationError as exc: raise HTTPException(status_code=401, detail=str(exc))
        except RepositoryError as exc: raise HTTPException(status_code=503, detail=str(exc))
    return {"organization_id": organization_id, "metrics": store.metrics, "events": store.events,
            "generated_at": datetime.now(timezone.utc).isoformat(), "data_mode":"DEMO"}

@app.get("/api/v1/organizations/{organization_id}/approvals")
def approvals(organization_id: str, status: Literal["PENDING","APPROVED","REJECTED","ALL"] = "PENDING", principal: Principal | None = Depends(require_dashboard_access)):
    if principal is not None:
        try:
            items = supabase_repository().approvals(principal, status)
            return {"items": items, "count": len(items), "data_mode":"SUPABASE_RLS"}
        except TenantAccessError as exc: raise HTTPException(status_code=403, detail=str(exc))
        except AuthenticationError as exc: raise HTTPException(status_code=401, detail=str(exc))
        except RepositoryError as exc: raise HTTPException(status_code=503, detail=str(exc))
    items = store.tenant_approvals(organization_id)
    if status != "ALL": items = [a for a in items if a["status"] == status]
    return {"items": items, "count": len(items), "data_mode":"DEMO"}

@app.post("/api/v1/organizations/{organization_id}/approvals/{approval_id}/resolve")
def resolve_approval(organization_id: str, approval_id: str, body: ApprovalResolution, principal: Principal | None = Depends(require_dashboard_access)):
    try:
        if principal is not None: return supabase_repository().resolve(principal, approval_id, body.approved, body.reason)
        return store.resolve(organization_id, approval_id, body.approved, body.reason)
    except KeyError: raise HTTPException(status_code=404, detail="Approval not found or already resolved")
    except RuntimeError as exc: raise HTTPException(status_code=409, detail=str(exc))
    except TenantAccessError as exc: raise HTTPException(status_code=403, detail=str(exc))
    except AuthenticationError as exc: raise HTTPException(status_code=401, detail=str(exc))
    except RepositoryError as exc: raise HTTPException(status_code=503, detail=str(exc))

@app.get("/api/v1/organizations/{organization_id}/executions")
def executions(organization_id: str, principal: Principal | None = Depends(require_dashboard_access)):
    if principal is not None:
        try: return {"items":supabase_repository().executions(principal), "data_mode":"SUPABASE_RLS"}
        except TenantAccessError as exc: raise HTTPException(status_code=403, detail=str(exc))
        except AuthenticationError as exc: raise HTTPException(status_code=401, detail=str(exc))
        except RepositoryError as exc: raise HTTPException(status_code=503, detail=str(exc))
    return {"items":[x for x in store.executions if x["organization_id"] == organization_id], "data_mode":"DEMO"}

@app.post("/api/v1/organizations/{organization_id}/leads")
def upsert_lead(organization_id: str, body: LeadUpsert,
                idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=250),
                principal: Principal | None = Depends(require_dashboard_access)):
    if principal is not None and principal.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Organization scope mismatch")
    try:
        result = lead_repository(principal).save_snapshot(
            organization_id=organization_id, lead_id=body.lead_id, state=body.state,
            payload=body.payload, event_type="LEAD_UPSERTED",
            idempotency_key=idempotency_key, expected_version=body.expected_version)
        return {**result, "data_mode": "SUPABASE_RLS" if os.getenv("APP_ENV", "pilot").lower() == "production" else "LOCAL_DURABLE_PILOT"}
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except LeadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.get("/api/v1/organizations/{organization_id}/leads")
def list_leads(organization_id: str, limit: int = 100,
               principal: Principal | None = Depends(require_dashboard_access)):
    if principal is not None and principal.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Organization scope mismatch")
    try:
        items = lead_repository(principal).list_leads(organization_id=organization_id, limit=limit)
        return {"items": items, "count": len(items), "data_mode": "SUPABASE_RLS" if os.getenv("APP_ENV", "pilot").lower() == "production" else "LOCAL_DURABLE_PILOT"}
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.get("/api/v1/organizations/{organization_id}/leads/{lead_id}")
def get_lead(organization_id: str, lead_id: str,
             principal: Principal | None = Depends(require_dashboard_access)):
    if principal is not None and principal.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Organization scope mismatch")
    try:
        item = lead_repository(principal).get_lead(organization_id=organization_id, lead_id=lead_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {**item, "data_mode": "SUPABASE_RLS" if os.getenv("APP_ENV", "pilot").lower() == "production" else "LOCAL_DURABLE_PILOT"}
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.get("/api/v1/organizations/{organization_id}/leads/{lead_id}/events")
def lead_events(organization_id: str, lead_id: str, limit: int = 200,
                principal: Principal | None = Depends(require_dashboard_access)):
    if principal is not None and principal.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Organization scope mismatch")
    try:
        if lead_repository(principal).get_lead(organization_id=organization_id, lead_id=lead_id) is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        items = lead_repository(principal).list_events(organization_id=organization_id, lead_id=lead_id, limit=limit)
        return {"items": items, "count": len(items), "data_mode": "SUPABASE_RLS" if os.getenv("APP_ENV", "pilot").lower() == "production" else "LOCAL_DURABLE_PILOT"}
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.get("/", response_class=HTMLResponse)
def dashboard_shell():
    return HTMLResponse('''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Sales System</title><link rel="stylesheet" href="/dashboard/dashboard.css"></head><body><header><div><p class="eyebrow">AI SALES SYSTEM / CONTROL PLANE</p><h1>CEO Dashboard</h1><p class="sub">Monitor automation, business health and human exceptions.</p></div><span class="mode">CONFIGURED MODE</span></header><main><section class="toolbar"><label>Organization ID <input id="org" value="org_demo"></label><label>API token <input id="token" type="password" placeholder="DASHBOARD_API_TOKEN"></label><button id="load">Load dashboard</button><p id="notice" role="status">Configure a dashboard API token to load protected data.</p></section><section class="metrics" id="metrics"><article><span>Total leads</span><strong>—</strong></article><article><span>Qualified leads</span><strong>—</strong></article><article><span>Active customers</span><strong>—</strong></article><article><span>Human intervention rate</span><strong>—</strong></article><article><span>AI cost this month</span><strong>—</strong></article><article><span>Automation success</span><strong>—</strong></article></section><div class="columns"><section class="panel"><div class="panel-head"><h2>Exception Center</h2><span>Human review queue</span></div><div id="approvals" class="empty">Load data to see pending approvals.</div></section><section class="panel"><div class="panel-head"><h2>Recent executions</h2><span>Runtime health</span></div><div id="executions" class="empty">Load data to see execution history.</div></section></div><p class="footnote">This release uses an in-memory demo repository. Do not use demo data for business decisions. Production requires authenticated tenant membership, durable repositories, RLS, audit logging and TLS.</p></main><script src="/dashboard/dashboard.js"></script></body></html>''')
