"""Supabase Auth + PostgREST dashboard repository.

Uses the caller's access token for all data access so PostgreSQL RLS remains active.
Never use the service-role key in this module.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
import httpx

class AuthenticationError(Exception): pass
class TenantAccessError(Exception): pass
class RepositoryError(Exception): pass

@dataclass(frozen=True)
class Principal:
    user_id: str
    organization_id: str
    role: str
    access_token: str

class SupabaseDashboardRepository:
    def __init__(self, *, url: str | None = None, anon_key: str | None = None, timeout: float = 8.0):
        self.url = (url or os.getenv('SUPABASE_URL', '')).rstrip('/')
        self.anon_key = anon_key or os.getenv('SUPABASE_ANON_KEY', '')
        self.timeout = timeout
        if not self.url or not self.anon_key:
            raise RepositoryError('SUPABASE_URL and SUPABASE_ANON_KEY must be configured')

    def _request(self, method: str, path: str, token: str, *, params=None, json=None, prefer=None):
        headers = {'apikey': self.anon_key, 'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
        if json is not None: headers['Content-Type'] = 'application/json'
        if prefer: headers['Prefer'] = prefer
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, f'{self.url}{path}', headers=headers, params=params, json=json)
        except httpx.HTTPError as exc:
            raise RepositoryError('Supabase request failed') from exc
        if response.status_code == 401: raise AuthenticationError('Supabase rejected the access token')
        if response.status_code == 403: raise TenantAccessError('Supabase denied access under tenant policy')
        if response.status_code >= 400:
            raise RepositoryError(f'Supabase returned HTTP {response.status_code}')
        if response.status_code == 204 or not response.content: return []
        try: return response.json()
        except ValueError as exc: raise RepositoryError('Supabase returned invalid JSON') from exc

    def authenticate(self, authorization: str | None, organization_id: str) -> Principal:
        if not authorization or not authorization.startswith('Bearer '):
            raise AuthenticationError('Bearer Supabase access token required')
        token = authorization[7:].strip()
        if not token: raise AuthenticationError('Bearer Supabase access token required')
        user = self._request('GET', '/auth/v1/user', token)
        user_id = user.get('id') if isinstance(user, dict) else None
        if not user_id: raise AuthenticationError('Supabase user identity missing')
        # RLS restricts this query to memberships visible to the authenticated user.
        rows = self._request('GET', '/rest/v1/organization_members', token, params={
            'select': 'organization_id,role', 'user_id': f'eq.{user_id}',
            'organization_id': f'eq.{organization_id}', 'limit': '1'
        })
        if not rows: raise TenantAccessError('User is not a member of this organization')
        role = str(rows[0].get('role', 'MEMBER')).upper()
        return Principal(user_id=user_id, organization_id=organization_id, role=role, access_token=token)

    def _rows(self, table: str, principal: Principal, *, select: str, params=None):
        query = {'select': select, 'organization_id': f'eq.{principal.organization_id}', **(params or {})}
        result = self._request('GET', f'/rest/v1/{table}', principal.access_token, params=query)
        if not isinstance(result, list): raise RepositoryError(f'Unexpected response for {table}')
        return result

    def overview(self, principal: Principal) -> dict[str, Any]:
        leads = self._rows('leads', principal, select='id,state')
        actions = self._rows('actions', principal, select='id,status,requires_approval,approved')
        events = self._rows('events', principal, select='type,created_at', params={'created_at': f'gte.{datetime.now(timezone.utc).replace(day=1).date().isoformat()}T00:00:00+00:00'})
        lifecycle = self._rows('customer_lifecycle_records', principal, select='customer_id,lifecycle_status', params={'lifecycle_status': 'eq.ACTIVE'})
        qualified_states = {'QUALIFIED', 'OFFER_PRESENTED', 'NEGOTIATING', 'PROPOSAL_SENT', 'PAYMENT_PENDING', 'WON', 'ONBOARDING', 'ACTIVE'}
        failed = sum(1 for event in events if event.get('type') in {'AUTOMATION_FAILED', 'WORKER_FAILED'})
        total_events = len(events)
        reviewed = sum(1 for action in actions if action.get('requires_approval'))
        metrics = {
            'leads_total': len(leads),
            'qualified': sum(1 for lead in leads if lead.get('state') in qualified_states),
            'customers_active': len(lifecycle),
            'human_intervention_rate': reviewed / len(actions) if actions else 0.0,
            'ai_cost_month_eur': 0.0,  # Usage-cost table is not part of the current schema; do not invent costs.
            'automation_success_rate': max(0.0, (total_events - failed) / total_events) if total_events else 1.0,
        }
        return {'organization_id': principal.organization_id, 'metrics': metrics, 'events': [],
                'generated_at': datetime.now(timezone.utc).isoformat(), 'data_mode': 'SUPABASE_RLS'}

    def approvals(self, principal: Principal, status: str = 'PENDING') -> list[dict[str, Any]]:
        params = {'order': 'created_at.desc'}
        if status != 'ALL': params['status'] = f'eq.{status}'
        rows = self._rows('approval_requests', principal,
            select='id,organization_id,action_type,summary,risk_level,status,created_at,resolved_at,resolution_reason', params=params)
        return [{**row, 'requested_at': row.get('created_at')} for row in rows]

    def executions(self, principal: Principal) -> list[dict[str, Any]]:
        rows = self._rows('execution_logs', principal,
            select='id,organization_id,workflow,status,duration_ms,created_at', params={'order':'created_at.desc','limit':'100'})
        return rows

    def resolve(self, principal: Principal, approval_id: str, approved: bool, reason: str) -> dict[str, Any]:
        if principal.role not in {'OWNER', 'ADMIN', 'MANAGER'}:
            raise TenantAccessError('Role does not permit resolving approvals')
        status = 'APPROVED' if approved else 'REJECTED'
        rows = self._request('POST', '/rest/v1/rpc/resolve_dashboard_approval', principal.access_token,
            json={'p_organization_id':principal.organization_id,'p_approval_id':approval_id,
                  'p_approved':approved,'p_reason':reason}, prefer='return=representation')
        if not rows: raise KeyError('approval not found or already resolved')
        row = rows[0]
        row['requested_at'] = row.get('created_at')
        return row
