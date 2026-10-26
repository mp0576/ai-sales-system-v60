from pathlib import Path
import pytest
from app.integrations.base import ProviderResult
from app.integrations.gateway import ActionContext, InternalActionGateway
from app.repositories.supabase_idempotency import SupabaseIdempotencyStore, IdempotencyStoreError

ROOT = Path(__file__).resolve().parents[1]

class FakeRepository:
    """Models atomic RPC decisions for local tests; not a substitute for live Postgres tests."""
    def __init__(self): self.records = {}; self.calls = []
    def _request(self, method, path, *, params=None, body=None, prefer=None):
        self.calls.append((method, path, body))
        key = (body['p_organization_id'], body['p_action_type'], body['p_idempotency_key'])
        if path.endswith('claim_action_idempotency'):
            row = self.records.get(key)
            if row and row['status'] in ('SUCCEEDED', 'FINAL_FAILURE'):
                return [{'decision':'REPLAY','result':row['result']}]
            if row and row['status'] == 'IN_PROGRESS':
                return [{'decision':'BUSY','result':None}]
            self.records[key] = {'status':'IN_PROGRESS','worker':body['p_worker_id'],'result':None}
            return [{'decision':'EXECUTE','result':None}]
        if path.endswith('finish_action_idempotency'):
            row = self.records[key]
            if row['worker'] != body['p_worker_id'] or row['status'] != 'IN_PROGRESS':
                raise RuntimeError('lease mismatch')
            row['result'] = body['p_result']
            row['status'] = ('RETRYABLE' if body['p_retryable'] else
                             'SUCCEEDED' if body['p_result']['ok'] else 'FINAL_FAILURE')
            return [{'status':row['status']}]
        raise AssertionError(path)


def test_store_replays_completed_result_across_gateway_instances():
    repo = FakeRepository(); store1 = SupabaseIdempotencyStore(repo); store2 = SupabaseIdempotencyStore(repo)
    calls = []
    def call():
        calls.append(1); return ProviderResult(True, 'whatsapp', external_id='provider-1', status='ACCEPTED')
    first = store1.execute_once(organization_id='org-a', action_type='message', idempotency_key='key-1', worker_id='w1', call=call)
    second = store2.execute_once(organization_id='org-a', action_type='message', idempotency_key='key-1', worker_id='w2', call=call)
    assert first == second and len(calls) == 1


def test_store_refuses_duplicate_while_another_worker_owns_lease():
    repo = FakeRepository(); store = SupabaseIdempotencyStore(repo); calls = []
    repo.records[('org-a','checkout','pay-1')] = {'status':'IN_PROGRESS','worker':'w1','result':None}
    result = store.execute_once(organization_id='org-a', action_type='checkout', idempotency_key='pay-1', worker_id='w2', call=lambda: calls.append(1))
    assert result.retryable and result.status == 'IN_PROGRESS' and calls == []


def test_retryable_result_can_be_reclaimed_and_completed():
    repo = FakeRepository(); store = SupabaseIdempotencyStore(repo); calls = []
    first = store.execute_once(organization_id='org-a', action_type='email', idempotency_key='e-1', worker_id='w1',
        call=lambda: (calls.append(1) or ProviderResult(False, 'email', status='RETRY', retryable=True)))
    assert first.retryable
    # Fake repository marks RETRYABLE; second claim allows execution.
    second = store.execute_once(organization_id='org-a', action_type='email', idempotency_key='e-1', worker_id='w2',
        call=lambda: (calls.append(1) or ProviderResult(True, 'email', external_id='email-1', status='SENT')))
    assert second.ok and len(calls) == 2


def test_gateway_uses_durable_store_for_shared_idempotency():
    repo = FakeRepository(); store = SupabaseIdempotencyStore(repo)
    class Provider:
        calls = 0
        def send(self, message):
            self.calls += 1
            return ProviderResult(True, 'whatsapp', external_id='wamid-1', status='ACCEPTED')
    provider = Provider()
    g1 = InternalActionGateway(messaging=provider, idempotency_store=store, worker_id='worker-a')
    g2 = InternalActionGateway(messaging=provider, idempotency_store=store, worker_id='worker-b')
    from app.integrations.base import OutboundMessage
    msg = OutboundMessage('org-a', '+351900000000', 'Hello', 'shared-key')
    ctx = ActionContext('org-a', outbound_enabled=True)
    assert g1.send_message(ctx, msg) == g2.send_message(ctx, msg)
    assert provider.calls == 1


def test_durable_idempotency_migration_is_service_role_only_and_tenant_scoped():
    sql = (ROOT / 'sql/migrations/0017_durable_action_idempotency.sql').read_text().lower()
    assert 'unique (organization_id, action_type, idempotency_key)' in sql
    assert 'for update' in sql
    assert 'from public, anon, authenticated' in sql
    assert 'to service_role' in sql


def test_release_gate_includes_v22_migration():
    from app.release.gate import static_checks
    checks = static_checks(ROOT)
    assert all(c.passed for c in checks), [(c.name, c.detail) for c in checks if not c.passed]

def test_process_local_fallback_scopes_same_key_by_tenant():
    from app.integrations.base import OutboundMessage
    from app.integrations.gateway import ActionContext, InternalActionGateway
    class Provider:
        def __init__(self): self.calls = []
        def send(self, message):
            self.calls.append(message.organization_id)
            return ProviderResult(True, 'whatsapp', external_id='id-' + message.organization_id, status='ACCEPTED')
    provider = Provider(); gateway = InternalActionGateway(messaging=provider)
    for org in ('org-a', 'org-b'):
        message = OutboundMessage(org, '+351900000000', 'Hi', 'same-key')
        gateway.send_message(ActionContext(org, outbound_enabled=True), message)
    assert provider.calls == ['org-a', 'org-b']
