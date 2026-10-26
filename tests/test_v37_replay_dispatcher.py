from app.workers.replay_dispatcher import ReplayDispatcher
from app.repositories.supabase_exceptions import OperationalExceptionStoreError

class FakeStore:
    def __init__(self, claim=..., finish_error=False):
        self.claim = ({"replay_request_id":"r1", "exception_id":"e1", "idempotency_key":"original-key", "replay_number":1, "failure_class":"TRANSIENT_NETWORK"} if claim is ... else claim)
        self.finish_error = finish_error
        self.claim_calls, self.finish_calls = [], []
    def claim_replay_dispatch(self, **kwargs):
        self.claim_calls.append(kwargs); return self.claim
    def finish_replay_dispatch(self, **kwargs):
        self.finish_calls.append(kwargs)
        if self.finish_error: raise OperationalExceptionStoreError("redacted")
        status = {"SUCCEEDED":"EXECUTED", "FAILED_DEFINITE":"FAILED", "OUTCOME_UNKNOWN":"RECONCILIATION_REQUIRED"}[kwargs["outcome"]]
        return {"status":status}

def test_only_claimed_approved_request_reaches_executor_and_preserves_key():
    store = FakeStore(); commands=[]
    result = ReplayDispatcher(store, lambda cmd: commands.append(cmd) or {"outcome":"SUCCEEDED", "result_code":"OK"}, worker_id="worker-1").dispatch_one(organization_id="org-1", replay_request_id="r1")
    assert result["status"] == "EXECUTED"
    assert commands[0]["idempotency_key"] == "original-key"
    assert store.finish_calls[0]["outcome"] == "SUCCEEDED"

def test_unclaimable_request_never_calls_executor():
    store = FakeStore(claim=None); called=[]
    result = ReplayDispatcher(store, lambda cmd: called.append(cmd), worker_id="w").dispatch_one(organization_id="o", replay_request_id="r")
    assert result["status"] == "NOT_DISPATCHED" and not called and not store.finish_calls

def test_executor_exception_becomes_reconciliation_not_blind_retry():
    store=FakeStore()
    def broken(_): raise TimeoutError("possibly sensitive provider response")
    result=ReplayDispatcher(store, broken, worker_id="w").dispatch_one(organization_id="o", replay_request_id="r")
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert store.finish_calls[0]["outcome"] == "OUTCOME_UNKNOWN"
    assert "possibly sensitive" not in str(result)

def test_finish_failure_is_reported_as_reconciliation():
    store=FakeStore(finish_error=True)
    result=ReplayDispatcher(store, lambda _: {"outcome":"SUCCEEDED"}, worker_id="w").dispatch_one(organization_id="o", replay_request_id="r")
    assert result == {"status":"RECONCILIATION_REQUIRED", "reason_code":"FINISH_PERSISTENCE_FAILED"}

def test_invalid_executor_result_fails_closed():
    store=FakeStore()
    result=ReplayDispatcher(store, lambda _: {"outcome":"RETRY_NOW"}, worker_id="w").dispatch_one(organization_id="o", replay_request_id="r")
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert store.finish_calls[0]["outcome"] == "OUTCOME_UNKNOWN"

def test_v37_migration_guards_atomic_claim_and_never_auto_replays_expired_lease():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "sql/migrations/0021_controlled_replay_dispatch.sql").read_text().lower()
    assert "for update skip locked" in sql
    assert "status='approved'" in sql
    assert "reconciliation_required" in sql
    assert "dispatch_lease_until < now()" in sql
    assert "revoke all on function public.claim_exception_replay" in sql
    assert "grant execute on function public.claim_exception_replay" in sql


def test_repository_claim_and_finish_use_service_rpc_contracts():
    from app.repositories.supabase_exceptions import SupabaseOperationalExceptionStore
    class Runtime:
        def __init__(self): self.calls=[]
        def _request(self, method, path, body=None, prefer=None):
            self.calls.append((method,path,body,prefer))
            return [{"replay_request_id":"r1", "exception_id":"e1", "idempotency_key":"key", "replay_number":1, "failure_class":"RATE_LIMITED"}] if path.endswith("claim_exception_replay") else [{"replay_request_id":"r1", "status":"EXECUTED"}]
    runtime=Runtime(); store=SupabaseOperationalExceptionStore(runtime)
    claim=store.claim_replay_dispatch(organization_id="o", replay_request_id="r1", worker_id="w", lease_seconds=60)
    finish=store.finish_replay_dispatch(organization_id="o", replay_request_id="r1", worker_id="w", outcome="SUCCEEDED", result_code="OK")
    assert claim["idempotency_key"] == "key" and finish["status"] == "EXECUTED"
    assert runtime.calls[0][1].endswith("claim_exception_replay")
    assert runtime.calls[1][2]["p_outcome"] == "SUCCEEDED"
