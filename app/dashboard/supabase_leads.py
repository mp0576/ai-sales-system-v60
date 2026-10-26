"""Supabase/PostgREST lead repository. Uses the caller's JWT; never service-role credentials."""
from __future__ import annotations
import os
from typing import Any
from urllib.parse import quote
import httpx
from app.repositories.real_estate_leads import LeadConflict, LeadRepositoryError, SQLiteLeadRepository

class SupabaseLeadRepository:
    def __init__(self, access_token: str, *, url: str | None = None, anon_key: str | None = None, timeout: float = 8.0):
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.anon_key = anon_key or os.getenv("SUPABASE_ANON_KEY", "")
        self.token = access_token
        self.timeout = timeout
        if not self.url or not self.anon_key or not self.token:
            raise LeadRepositoryError("Supabase URL, anon key and caller access token are required")

    def _request(self, method: str, path: str, *, params=None, body=None, prefer=None):
        headers = {"apikey": self.anon_key, "Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if body is not None: headers["Content-Type"] = "application/json"
        if prefer: headers["Prefer"] = prefer
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.request(method, self.url + path, headers=headers, params=params, json=body)
        except httpx.HTTPError as exc:
            raise LeadRepositoryError("Supabase lead request failed") from exc
        if r.status_code in (400, 409, 422):
            # PostgREST commonly returns SQLSTATE 23505 (unique_violation) for
            # reused idempotency keys and 40001 (serialization_failure) for stale
            # versions. Normalize these into the repository conflict contract.
            try:
                error_body = r.json()
            except ValueError:
                error_body = {}
            code = str(error_body.get("code", "")) if isinstance(error_body, dict) else ""
            message = str(error_body.get("message", "")) if isinstance(error_body, dict) else ""
            if code in {"23505", "40001", "P0001"} or "idempotency key reused" in message.lower() or "version conflict" in message.lower():
                raise LeadConflict("Lead version or idempotency conflict")
        if r.status_code in (401, 403):
            raise LeadRepositoryError("Supabase rejected lead access under authentication/RLS")
        if r.status_code >= 400:
            raise LeadRepositoryError(f"Supabase lead endpoint returned HTTP {r.status_code}")
        if not r.content: return []
        try: return r.json()
        except ValueError as exc: raise LeadRepositoryError("Supabase returned invalid JSON") from exc

    def save_snapshot(self, *, organization_id: str, lead_id: str, state: str, payload: dict[str, Any],
                      event_type: str = "LEAD_SNAPSHOT_SAVED", idempotency_key: str, expected_version: int | None = None):
        result = self._request("POST", "/rest/v1/rpc/save_operational_lead_snapshot", body={
            "p_organization_id": organization_id, "p_lead_id": lead_id, "p_state": state,
            "p_payload": payload, "p_event_type": event_type, "p_idempotency_key": idempotency_key,
            "p_expected_version": expected_version})
        if isinstance(result, list): result = result[0] if result else {}
        if not isinstance(result, dict): raise LeadRepositoryError("Unexpected lead RPC response")
        if result.get("conflict"): raise LeadConflict(str(result.get("message", "Lead conflict")))
        return result

    def get_lead(self, *, organization_id: str, lead_id: str):
        rows = self._request("GET", "/rest/v1/operational_lead_snapshots", params={
            "select":"organization_id,lead_id,state,payload,version,created_at,updated_at",
            "organization_id":f"eq.{organization_id}", "lead_id":f"eq.{lead_id}", "limit":"1"})
        return rows[0] if rows else None

    def list_leads(self, *, organization_id: str, limit: int = 100):
        if not 1 <= limit <= 500: raise ValueError("limit must be between 1 and 500")
        return self._request("GET", "/rest/v1/operational_lead_snapshots", params={
            "select":"organization_id,lead_id,state,payload,version,created_at,updated_at",
            "organization_id":f"eq.{organization_id}", "order":"updated_at.desc,lead_id.asc", "limit":str(limit)})

    def list_events(self, *, organization_id: str, lead_id: str, limit: int = 200):
        if not 1 <= limit <= 1000: raise ValueError("limit must be between 1 and 1000")
        return self._request("GET", "/rest/v1/operational_lead_events", params={
            "select":"event_id,organization_id,lead_id,event_type,event_payload,created_at",
            "organization_id":f"eq.{organization_id}", "lead_id":f"eq.{lead_id}",
            "order":"created_at.asc,event_id.asc", "limit":str(limit)})
