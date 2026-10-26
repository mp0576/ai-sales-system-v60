from app.dashboard.supabase_leads import SupabaseLeadRepository

class Response:
    status_code = 200
    content = b'{"duplicate":false,"version":1,"lead":{"lead_id":"L-1"}}'
    def json(self):
        import json
        return json.loads(self.content)


def test_hosted_adapter_uses_caller_jwt_and_atomic_rpc(monkeypatch):
    captured = {}
    class Client:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, method, url, headers, params=None, json=None):
            captured.update(method=method, url=url, headers=headers, body=json)
            return Response()
    import app.dashboard.supabase_leads as module
    monkeypatch.setattr(module.httpx, 'Client', Client)
    repo = SupabaseLeadRepository('user-access-token', url='https://project.supabase.co', anon_key='public-anon-key')
    result = repo.save_snapshot(organization_id='00000000-0000-0000-0000-000000000001', lead_id='L-1',
        state='NEW', payload={}, idempotency_key='test-idempotency-1', expected_version=0)
    assert result['version'] == 1
    assert captured['method'] == 'POST'
    assert captured['url'].endswith('/rest/v1/rpc/save_operational_lead_snapshot')
    assert captured['headers']['Authorization'] == 'Bearer user-access-token'
    assert 'service_role' not in str(captured['headers']).lower()
    assert captured['body']['p_idempotency_key'] == 'test-idempotency-1'
