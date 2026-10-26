import pytest
from app.repositories.supabase_exceptions import SupabaseOperationalExceptionStore, OperationalExceptionStoreError
from app.repositories.supabase_runtime import RuntimeRepositoryError

class FakeRuntime:
    def __init__(self, response=None, error=None):
        self.response = response or [{"replay_request_id": "req-1", "status": "PENDING_APPROVAL", "duplicate": False}]
        self.error = error
        self.calls = []
    def _request(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body, prefer))
        if self.error:
            raise self.error
        return self.response

def test_request_replay_persists_original_key_and_not_dispatch():
    repo = FakeRuntime()
    store = SupabaseOperationalExceptionStore(repo)
    result = store.request_replay(organization_id="org-1", exception_id="ex-1", actor_user_id="u-1",
        replay_number=1, failure_class="TRANSIENT_NETWORK", external_outcome="NOT_APPLIED",
        idempotency_key="same-key", reason="Provider confirmed no operation was applied")
    assert result["status"] == "PENDING_APPROVAL"
    method, path, body, _ = repo.calls[0]
    assert method == "POST" and path.endswith("request_exception_replay")
    assert body["p_idempotency_key"] == "same-key"
    assert "dispatch" not in path

def test_request_replay_rejects_unsafe_inputs_before_rpc():
    repo = FakeRuntime()
    store = SupabaseOperationalExceptionStore(repo)
    base = dict(organization_id="org-1", exception_id="ex-1", actor_user_id="u-1", replay_number=1,
        failure_class="TRANSIENT_NETWORK", external_outcome="NOT_APPLIED", idempotency_key="key", reason="reviewed")
    with pytest.raises(ValueError): store.request_replay(**{**base, "external_outcome": "UNKNOWN"})
    with pytest.raises(ValueError): store.request_replay(**{**base, "failure_class": "PERMANENT"})
    with pytest.raises(ValueError): store.request_replay(**{**base, "replay_number": 11})
    assert repo.calls == []

def test_decision_requires_boolean_and_note():
    repo = FakeRuntime(response=[{"replay_request_id": "req-1", "status": "APPROVED"}])
    store = SupabaseOperationalExceptionStore(repo)
    with pytest.raises(ValueError):
        store.decide_replay(organization_id="org-1", replay_request_id="req-1", actor_user_id="u-2", approve="yes", note="ok")
    with pytest.raises(ValueError):
        store.decide_replay(organization_id="org-1", replay_request_id="req-1", actor_user_id="u-2", approve=True, note=" ")
    result = store.decide_replay(organization_id="org-1", replay_request_id="req-1", actor_user_id="u-2", approve=True, note="independent approval")
    assert result["status"] == "APPROVED"
    assert repo.calls[0][2]["p_actor_user_id"] == "u-2"

def test_repository_errors_are_redacted():
    repo = FakeRuntime(error=RuntimeRepositoryError("raw provider detail / secret"))
    store = SupabaseOperationalExceptionStore(repo)
    with pytest.raises(OperationalExceptionStoreError) as caught:
        store.request_replay(organization_id="org-1", exception_id="ex-1", actor_user_id="u-1",
            replay_number=1, failure_class="RATE_LIMITED", external_outcome="NOT_APPLIED",
            idempotency_key="key", reason="retry requested")
    assert "raw provider detail" not in str(caught.value)
