"""Application-level tests for automatic dead-letter exception persistence.

Uses fake repositories; SQL transaction and hosted Supabase behavior remain staging checks.
"""
from app.orchestrator.runtime import EventDispatcher
from app.workers.durable_service import DurableWorkerConfig, DurableWorkerService
from tests.test_v24_runtime_integration import FakeOutboxRepository, event


class FakeExceptionStore:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"exception_id": "exception-1", "status": "OPEN", "duplicate": False}


def test_permanent_dispatch_failure_creates_safe_tenant_scoped_exception():
    repo = FakeOutboxRepository([event(topic="missing.handler", payload={"email": "private@example.com"})])
    store = FakeExceptionStore()
    worker = DurableWorkerService(repo, EventDispatcher(), config=DurableWorkerConfig("worker-a"), exception_store=store)
    result = worker.run_once()
    assert result["failed"] == 1
    assert result["exceptions_persisted"] == 1 and result["exception_errors"] == 0
    assert store.calls == [{
        "organization_id": "org-a", "source_type": "outbox", "source_id": "outbox-evt-1",
        "code": "DEAD_LETTER", "severity": "HIGH",
        "summary": "Work item exhausted retries or failed permanently; review before replay",
    }]
    assert "private@example.com" not in str(store.calls)


def test_transient_failure_does_not_create_exception_before_retry_budget_exhausted():
    def broken(ctx, payload):
        raise RuntimeError("provider secret and PII")
    repo = FakeOutboxRepository([event()])
    store = FakeExceptionStore()
    worker = DurableWorkerService(repo, EventDispatcher({"lead.created": broken}),
        config=DurableWorkerConfig("worker-a", max_attempts=5), exception_store=store)
    result = worker.run_once()
    assert result["retrying"] == 1 and result["exceptions_persisted"] == 0
    assert store.calls == []


def test_retry_budget_exhaustion_dead_letters_and_creates_exception():
    def broken(ctx, payload):
        raise RuntimeError("provider secret")
    repo = FakeOutboxRepository([event()])
    store = FakeExceptionStore()
    worker = DurableWorkerService(repo, EventDispatcher({"lead.created": broken}),
        config=DurableWorkerConfig("worker-a", max_attempts=2), exception_store=store)
    result = worker.run_once()
    assert result["failed"] == 1 and result["retrying"] == 0
    assert repo.rows[0]["status"] == "DEAD_LETTER"
    assert len(store.calls) == 1 and store.calls[0]["source_id"] == "outbox-evt-1"


def test_exception_store_failure_does_not_change_committed_dead_letter_outcome():
    repo = FakeOutboxRepository([event(topic="missing.handler")])
    store = FakeExceptionStore(error=RuntimeError("database details must not leak"))
    worker = DurableWorkerService(repo, EventDispatcher(), config=DurableWorkerConfig("worker-a"), exception_store=store)
    result = worker.run_once()
    assert result["failed"] == 1 and result["exception_errors"] == 1
    assert repo.rows[0]["status"] == "DEAD_LETTER"


def test_worker_without_exception_store_preserves_legacy_summary_contract():
    repo = FakeOutboxRepository([event()])
    worker = DurableWorkerService(repo, EventDispatcher({"lead.created": lambda ctx, payload: {"ok": True}}),
        config=DurableWorkerConfig("worker-a"))
    result = worker.run_once()
    assert result == {"claimed": 1, "succeeded": 1, "retrying": 0, "failed": 0, "lease_rejected": 0}
