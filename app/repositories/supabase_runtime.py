"""Server-side durable runtime repository for Supabase/PostgREST.

Use only from trusted backend/worker processes. The service-role key bypasses RLS,
so every method requires an explicit organization_id and applies tenant filters.
Multi-table atomic operations are implemented as PostgreSQL RPC functions.
"""
from __future__ import annotations
import os
from typing import Any
import httpx

class RuntimeRepositoryError(RuntimeError):
    pass

class RuntimeConfigurationError(RuntimeRepositoryError):
    pass

class SupabaseRuntimeRepository:
    def __init__(self, *, url: str | None = None, service_role_key: str | None = None, timeout: float = 10.0):
        self.url = (url if url is not None else os.getenv('SUPABASE_URL', '')).rstrip('/')
        self.key = service_role_key if service_role_key is not None else os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
        self.timeout = timeout
        if not self.url or not self.key:
            raise RuntimeConfigurationError('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for runtime persistence')
        if self.key.startswith('sb_publishable_') or self.key == os.getenv('SUPABASE_ANON_KEY'):
            raise RuntimeConfigurationError('A server-only service role key is required; public/anon keys are not accepted')

    def _request(self, method: str, path: str, *, params=None, body=None, prefer: str | None = None):
        headers = {'apikey': self.key, 'Authorization': f'Bearer {self.key}', 'Accept': 'application/json'}
        if body is not None: headers['Content-Type'] = 'application/json'
        if prefer: headers['Prefer'] = prefer
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, self.url + path, headers=headers, params=params, json=body)
        except httpx.HTTPError as exc:
            raise RuntimeRepositoryError('Supabase runtime request failed') from exc
        if response.status_code >= 400:
            # Do not surface response bodies: they may contain user data or SQL details.
            raise RuntimeRepositoryError(f'Supabase runtime returned HTTP {response.status_code}')
        if response.status_code == 204 or not response.content: return []
        try: return response.json()
        except ValueError as exc: raise RuntimeRepositoryError('Supabase returned invalid JSON') from exc

    @staticmethod
    def _require_tenant(organization_id: str):
        if not isinstance(organization_id, str) or not organization_id.strip():
            raise ValueError('organization_id is required for every runtime operation')

    def create_lead(self, *, organization_id: str, state: str = 'NEW', contact_id: str | None = None,
                    facts: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None,
                    idempotency_key: str):
        self._require_tenant(organization_id)
        if not idempotency_key or len(idempotency_key) > 200: raise ValueError('valid idempotency_key is required')
        body = {'p_organization_id': organization_id, 'p_state': state, 'p_contact_id': contact_id,
                'p_facts': facts or {}, 'p_metadata': metadata or {}, 'p_idempotency_key': idempotency_key}
        rows = self._request('POST', '/rest/v1/rpc/create_lead_with_event', body=body, prefer='return=representation')
        if not isinstance(rows, list) or not rows: raise RuntimeRepositoryError('Lead creation RPC returned no result')
        return rows[0]

    def append_event(self, *, organization_id: str, event_type: str, payload: dict[str, Any] | None = None,
                     lead_id: str | None = None, idempotency_key: str, topic: str | None = None):
        self._require_tenant(organization_id)
        if not event_type.strip(): raise ValueError('event_type is required')
        if not idempotency_key or len(idempotency_key) > 200: raise ValueError('valid idempotency_key is required')
        rows = self._request('POST', '/rest/v1/rpc/append_event_to_outbox', body={
            'p_organization_id': organization_id, 'p_event_type': event_type, 'p_payload': payload or {},
            'p_lead_id': lead_id, 'p_idempotency_key': idempotency_key, 'p_topic': topic or event_type.lower()
        }, prefer='return=representation')
        if not isinstance(rows, list) or not rows: raise RuntimeRepositoryError('Event RPC returned no result')
        return rows[0]

    def record_action(self, *, organization_id: str, action_type: str, lead_id: str | None = None,
                      input_data: dict[str, Any] | None = None, idempotency_key: str,
                      requires_approval: bool = False):
        self._require_tenant(organization_id)
        if not idempotency_key or len(idempotency_key) > 200: raise ValueError('valid idempotency_key is required')
        body = {'organization_id': organization_id, 'action_type': action_type, 'lead_id': lead_id,
                'input': input_data or {}, 'idempotency_key': idempotency_key,
                'requires_approval': requires_approval, 'approved': not requires_approval,
                'status': 'PENDING_APPROVAL' if requires_approval else 'PENDING'}
        rows = self._request('POST', '/rest/v1/actions', body=body, prefer='resolution=ignore-duplicates,return=representation')
        if rows: return rows[0]
        found = self._request('GET', '/rest/v1/actions', params={'select':'*','organization_id':f'eq.{organization_id}',
            'idempotency_key':f'eq.{idempotency_key}','limit':'1'})
        if not found: raise RuntimeRepositoryError('Idempotent action was not returned or found')
        return {**found[0], 'duplicate': True}

    def claim_outbox(self, *, worker_id: str, batch_size: int = 10, lease_seconds: int = 120):
        if not worker_id.strip(): raise ValueError('worker_id is required')
        if not 1 <= batch_size <= 100: raise ValueError('batch_size must be between 1 and 100')
        if not 15 <= lease_seconds <= 3600: raise ValueError('lease_seconds must be between 15 and 3600')
        rows = self._request('POST', '/rest/v1/rpc/claim_outbox', body={
            'batch_size': batch_size, 'worker_id': worker_id, 'lease_seconds': lease_seconds
        }, prefer='return=representation')
        if not isinstance(rows, list): raise RuntimeRepositoryError('Outbox claim returned invalid result')
        return rows

    def finish_outbox(self, *, organization_id: str, outbox_id: str, worker_id: str,
                      succeeded: bool, error: str | None = None, retry_delay_seconds: int = 30, permanent: bool = False):
        self._require_tenant(organization_id)
        if not worker_id.strip(): raise ValueError('worker_id is required')
        rows = self._request('POST', '/rest/v1/rpc/finish_outbox', body={
            'p_organization_id': organization_id, 'p_outbox_id': outbox_id, 'p_worker_id': worker_id,
            'p_succeeded': succeeded, 'p_error': (error or '')[:1000],
            'p_retry_delay_seconds': max(1, min(int(retry_delay_seconds), 86400)), 'p_permanent': bool(permanent)
        }, prefer='return=representation')
        if not isinstance(rows, list) or not rows: raise RuntimeRepositoryError('Outbox completion rejected: lease/tenant mismatch or missing row')
        return rows[0]
