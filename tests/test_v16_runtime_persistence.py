import pytest
from app.repositories.supabase_runtime import SupabaseRuntimeRepository, RuntimeConfigurationError


def repo():
    return SupabaseRuntimeRepository(url='https://example.supabase.co', service_role_key='server-only-test-key')


def test_runtime_requires_server_credentials(monkeypatch):
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    with pytest.raises(RuntimeConfigurationError): SupabaseRuntimeRepository(url='', service_role_key='')


def test_runtime_rejects_public_key():
    with pytest.raises(RuntimeConfigurationError):
        SupabaseRuntimeRepository(url='https://example.supabase.co', service_role_key='sb_publishable_public')


def test_create_lead_calls_atomic_rpc_and_returns_row(monkeypatch):
    r=repo(); seen={}
    def request(method,path,**kwargs):
        seen.update(method=method,path=path,kwargs=kwargs)
        return [{'lead_id':'l1','event_id':'e1','outbox_id':'o1','duplicate':False}]
    monkeypatch.setattr(r,'_request',request)
    result=r.create_lead(organization_id='org-1',idempotency_key='lead:seed:1',facts={'source':'web'})
    assert result['lead_id']=='l1'
    assert seen['path']=='/rest/v1/rpc/create_lead_with_event'
    assert seen['kwargs']['body']['p_organization_id']=='org-1'


def test_append_event_is_atomic_rpc_and_scoped(monkeypatch):
    r=repo(); seen={}
    monkeypatch.setattr(r,'_request',lambda method,path,**kwargs: (seen.update(method=method,path=path,kwargs=kwargs) or [{'event_id':'e1','outbox_id':'o1','duplicate':True}]))
    row=r.append_event(organization_id='org-1',event_type='MESSAGE_RECEIVED',lead_id='lead-1',payload={'safe':True},idempotency_key='msg:123')
    assert row['duplicate'] is True
    assert seen['path']=='/rest/v1/rpc/append_event_to_outbox'
    assert seen['kwargs']['body']['p_organization_id']=='org-1'


def test_record_action_deduplicates_by_org_and_idempotency(monkeypatch):
    r=repo(); calls=[]
    def request(method,path,**kwargs):
        calls.append((method,path,kwargs))
        if method=='POST': return []
        return [{'id':'a1','organization_id':'org-1','idempotency_key':'same-key'}]
    monkeypatch.setattr(r,'_request',request)
    row=r.record_action(organization_id='org-1',action_type='SEND_MESSAGE',idempotency_key='same-key')
    assert row['duplicate'] is True
    assert calls[1][2]['params']['organization_id']=='eq.org-1'


def test_claim_outbox_bounds_batch_and_lease(monkeypatch):
    r=repo()
    with pytest.raises(ValueError): r.claim_outbox(worker_id='worker',batch_size=1000)
    with pytest.raises(ValueError): r.claim_outbox(worker_id='worker',lease_seconds=1)
    monkeypatch.setattr(r,'_request',lambda *a,**kw: [])
    assert r.claim_outbox(worker_id='worker-1',batch_size=5)==[]


def test_finish_outbox_requires_owned_lease(monkeypatch):
    r=repo(); seen={}
    monkeypatch.setattr(r,'_request',lambda method,path,**kwargs: (seen.update(path=path,body=kwargs['body']) or [{'status':'COMPLETED'}]))
    row=r.finish_outbox(organization_id='org-1',outbox_id='o1',worker_id='worker-1',succeeded=True)
    assert row['status']=='COMPLETED'
    assert seen['path']=='/rest/v1/rpc/finish_outbox'
    assert seen['body']['p_worker_id']=='worker-1'


def test_tenant_required_for_every_write(monkeypatch):
    r=repo()
    with pytest.raises(ValueError): r.append_event(organization_id='',event_type='X',idempotency_key='x')
    with pytest.raises(ValueError): r.record_action(organization_id='org-1',action_type='X',idempotency_key='')


def test_runtime_errors_do_not_expose_provider_body(monkeypatch):
    import httpx
    r=repo()
    class Response:
        status_code=500; content=b'{}'
        def json(self): return {'secret':'no'}
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def request(self,*args,**kwargs): return Response()
    monkeypatch.setattr(httpx,'Client',Client)
    with pytest.raises(Exception) as err: r._request('GET','/rest/v1/leads')
    assert 'secret' not in str(err.value)
