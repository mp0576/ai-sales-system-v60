import os
import pytest
from fastapi.testclient import TestClient
from app.dashboard.api import app, store

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DASHBOARD_API_TOKEN','test-secret')
    return TestClient(app)

def auth(): return {'Authorization':'Bearer test-secret'}

def test_health_is_public(client):
    assert client.get('/health').json()['status'] == 'ok'

def test_api_fails_closed_without_config(client, monkeypatch):
    monkeypatch.delenv('DASHBOARD_API_TOKEN', raising=False)
    assert client.get('/api/v1/organizations/org_demo/overview').status_code == 503

def test_api_requires_bearer_token(client):
    assert client.get('/api/v1/organizations/org_demo/overview').status_code == 401

def test_overview_requires_auth_and_marks_demo(client):
    response=client.get('/api/v1/organizations/org_demo/overview',headers=auth())
    assert response.status_code == 200
    assert response.json()['data_mode'] == 'DEMO'
    assert response.json()['metrics']['leads_total'] > 0

def test_approvals_are_tenant_filtered(client):
    data=client.get('/api/v1/organizations/org_demo/approvals',headers=auth()).json()
    assert data['count'] == 2
    other=client.get('/api/v1/organizations/org_other/approvals?status=ALL',headers=auth()).json()
    assert other['count'] == 0

def test_approval_resolution_and_audit_fields(client):
    response=client.post('/api/v1/organizations/org_demo/approvals/apr_demo_001/resolve',headers=auth(),json={'approved':False,'reason':'Outside policy limit'})
    assert response.status_code == 200
    assert response.json()['status'] == 'REJECTED'
    assert response.json()['resolution_reason'] == 'Outside policy limit'

def test_approval_cannot_be_resolved_twice(client):
    payload={'approved':True,'reason':'Verified within policy'}
    first=client.post('/api/v1/organizations/org_demo/approvals/apr_demo_002/resolve',headers=auth(),json=payload)
    second=client.post('/api/v1/organizations/org_demo/approvals/apr_demo_002/resolve',headers=auth(),json=payload)
    assert first.status_code == 200 and second.status_code == 409

def test_unknown_or_cross_tenant_approval_is_not_found(client):
    response=client.post('/api/v1/organizations/org_other/approvals/apr_demo_001/resolve',headers=auth(),json={'approved':True,'reason':'Should not resolve'})
    assert response.status_code == 404

def test_executions_are_tenant_filtered(client):
    data=client.get('/api/v1/organizations/org_demo/executions',headers=auth()).json()
    assert len(data['items']) == 3
    other=client.get('/api/v1/organizations/org_other/executions',headers=auth()).json()
    assert other['items'] == []

def test_dashboard_shell_and_assets_are_served(client):
    page=client.get('/')
    assert page.status_code == 200 and 'CEO Dashboard' in page.text
    css=client.get('/dashboard/dashboard.css')
    js=client.get('/dashboard/dashboard.js')
    assert css.status_code == 200 and 'Exception Center' not in css.text
    assert js.status_code == 200 and 'function load()' in js.text
