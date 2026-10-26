import os
import pytest
from fastapi.testclient import TestClient
from app.dashboard import api
from app.dashboard.supabase_store import (
    SupabaseDashboardRepository, Principal, AuthenticationError, TenantAccessError,
)

class FakeRepository:
    def authenticate(self, authorization, organization_id):
        if authorization != 'Bearer valid-user-token':
            raise AuthenticationError('Supabase rejected the access token or permission')
        if organization_id != 'org-member':
            raise TenantAccessError('User is not a member of this organization')
        return Principal('user-1', organization_id, 'OWNER', 'valid-user-token')
    def overview(self, principal):
        return {'organization_id': principal.organization_id, 'data_mode':'SUPABASE_RLS', 'metrics':{'leads_total':0}}
    def approvals(self, principal, status='PENDING'): return []
    def executions(self, principal): return []
    def resolve(self, *args, **kwargs): raise KeyError('approval not found or already resolved')


def test_supabase_auth_requires_bearer_token(monkeypatch):
    repo = SupabaseDashboardRepository(url='https://example.supabase.co', anon_key='anon')
    with pytest.raises(AuthenticationError): repo.authenticate(None, 'org')
    with pytest.raises(AuthenticationError): repo.authenticate('Bearer ', 'org')


def test_supabase_auth_verifies_user_then_membership(monkeypatch):
    repo = SupabaseDashboardRepository(url='https://example.supabase.co', anon_key='anon')
    calls=[]
    def fake_request(method, path, token, **kwargs):
        calls.append((method,path,token,kwargs))
        if path == '/auth/v1/user': return {'id':'user-1'}
        return [{'organization_id':'org-1','role':'ADMIN'}]
    monkeypatch.setattr(repo, '_request', fake_request)
    principal=repo.authenticate('Bearer access-token','org-1')
    assert principal.user_id == 'user-1' and principal.role == 'ADMIN'
    assert calls[0][1] == '/auth/v1/user'
    assert calls[1][1] == '/rest/v1/organization_members'
    assert calls[1][3]['params']['user_id'] == 'eq.user-1'


def test_supabase_auth_denies_non_member(monkeypatch):
    repo = SupabaseDashboardRepository(url='https://example.supabase.co', anon_key='anon')
    monkeypatch.setattr(repo, '_request', lambda method, path, token, **kwargs: {'id':'user-1'} if path == '/auth/v1/user' else [])
    with pytest.raises(TenantAccessError): repo.authenticate('Bearer token','org-other')


def test_production_dashboard_rejects_static_demo_token(monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('DASHBOARD_API_TOKEN','demo-static-token')
    monkeypatch.setattr(api, 'supabase_repository', lambda: FakeRepository())
    client=TestClient(api.app)
    response=client.get('/api/v1/organizations/org-member/overview',headers={'Authorization':'Bearer demo-static-token'})
    assert response.status_code == 401


def test_production_dashboard_requires_real_tenant_membership(monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setattr(api, 'supabase_repository', lambda: FakeRepository())
    client=TestClient(api.app)
    response=client.get('/api/v1/organizations/org-other/overview',headers={'Authorization':'Bearer valid-user-token'})
    assert response.status_code == 403


def test_production_dashboard_uses_verified_supabase_principal(monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setattr(api, 'supabase_repository', lambda: FakeRepository())
    client=TestClient(api.app)
    response=client.get('/api/v1/organizations/org-member/overview',headers={'Authorization':'Bearer valid-user-token'})
    assert response.status_code == 200
    assert response.json()['organization_id'] == 'org-member'
    assert response.json()['data_mode'] == 'SUPABASE_RLS'
