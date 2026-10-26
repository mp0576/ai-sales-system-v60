"""Integration-contract tests for dispatcher + durable worker glue.

The repository is a deterministic thread-safe test double. These tests exercise
application-layer wiring, not PostgreSQL transaction semantics or hosted providers.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import pytest

from app.orchestrator.runtime import EventDispatcher, EventRejected, HandlerUnavailable
from app.workers.durable_service import DurableWorkerConfig, DurableWorkerService


class FakeOutboxRepository:
    def __init__(self, rows=None):
        self.lock = Lock()
        self.rows = [dict(r) for r in (rows or [])]
        self.finish_calls = []

    def claim_outbox(self, *, worker_id, batch_size=10, lease_seconds=120):
        with self.lock:
            claimed = []
            for row in self.rows:
                if row.get("status", "PENDING") == "PENDING" and len(claimed) < batch_size:
                    row["status"] = "PROCESSING"
                    row["worker_id"] = worker_id
                    row["attempts"] = int(row.get("attempts", 0)) + 1
                    claimed.append(dict(row))
            return claimed

    def finish_outbox(self, *, organization_id, outbox_id, worker_id, succeeded,
                      error=None, retry_delay_seconds=30, permanent=False):
        with self.lock:
            row = next((r for r in self.rows if str(r["id"]) == str(outbox_id)), None)
            if not row or row.get("organization_id") != organization_id or row.get("worker_id") != worker_id or row.get("status") != "PROCESSING":
                raise RuntimeError("lease/tenant mismatch")
            row["status"] = "SUCCEEDED" if succeeded else ("DEAD_LETTER" if permanent else "PENDING")
            row["last_error"] = error
            row["retry_delay_seconds"] = retry_delay_seconds
            self.finish_calls.append((outbox_id, worker_id, succeeded, permanent))
            return {"status": row["status"]}


def event(event_id="evt-1", org="org-a", topic="lead.created", payload=None):
    return {"id": f"outbox-{event_id}", "event_id": event_id, "organization_id": org,
            "topic": topic, "payload": payload or {}, "attempts": 1, "status": "PENDING"}


def worker(repo, dispatcher, worker_id="worker-a"):
    return DurableWorkerService(repo, dispatcher, config=DurableWorkerConfig(
        worker_id=worker_id, batch_size=10, lease_seconds=60, max_attempts=5))


def test_golden_event_path_dispatches_and_marks_outbox_succeeded():
    seen = []
    dispatcher = EventDispatcher({"lead.created": lambda ctx, payload: seen.append((ctx.organization_id, payload["lead_id"])) or {"accepted": True}})
    repo = FakeOutboxRepository([event(payload={"lead_id": "lead-1"})])
    result = worker(repo, dispatcher).run_once()
    assert result == {"claimed": 1, "succeeded": 1, "retrying": 0, "failed": 0, "lease_rejected": 0}
    assert seen == [("org-a", "lead-1")]
    assert repo.rows[0]["status"] == "SUCCEEDED"


def test_event_payload_cannot_override_durable_tenant_context():
    dispatcher = EventDispatcher({"lead.created": lambda ctx, payload: {"ok": True}})
    repo = FakeOutboxRepository([event(payload={"organization_id": "org-b"})])
    result = worker(repo, dispatcher).run_once()
    assert result["failed"] == 1
    assert repo.rows[0]["status"] == "DEAD_LETTER"


def test_missing_handler_is_dead_lettered_without_retry_loop():
    repo = FakeOutboxRepository([event(topic="unknown.topic")])
    result = worker(repo, EventDispatcher()).run_once()
    assert result["failed"] == 1 and result["retrying"] == 0
    assert repo.rows[0]["status"] == "DEAD_LETTER"


def test_unexpected_handler_error_is_rescheduled_with_backoff_and_safe_error():
    def broken(ctx, payload):
        raise RuntimeError("private payload and secret should not be logged")
    repo = FakeOutboxRepository([event()])
    result = worker(repo, EventDispatcher({"lead.created": broken})).run_once()
    assert result["retrying"] == 1
    assert repo.rows[0]["status"] == "PENDING"
    assert repo.rows[0]["retry_delay_seconds"] == 10
    assert "secret" not in repo.rows[0]["last_error"]
    assert "private payload" not in repo.rows[0]["last_error"]


def test_handler_can_request_retry_and_worker_reschedules():
    from app.orchestrator.runtime import DispatchResult
    repo = FakeOutboxRepository([event()])
    dispatcher = EventDispatcher({"lead.created": lambda ctx, payload: DispatchResult("RETRY", error="temporary")})
    result = worker(repo, dispatcher).run_once()
    assert result["retrying"] == 1
    assert repo.rows[0]["status"] == "PENDING"


def test_lease_loss_is_counted_not_reported_as_success():
    class LeaseLossRepo(FakeOutboxRepository):
        def finish_outbox(self, **kwargs):
            raise RuntimeError("lease expired")
    repo = LeaseLossRepo([event()])
    result = worker(repo, EventDispatcher({"lead.created": lambda ctx, payload: {"ok": True}})).run_once()
    assert result["lease_rejected"] == 1
    assert result["succeeded"] == 0


def test_same_event_claimed_by_concurrent_test_workers_has_one_claim_owner():
    repo = FakeOutboxRepository([event()])
    def claim(worker_id):
        return repo.claim_outbox(worker_id=worker_id, batch_size=1, lease_seconds=60)
    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(claim, [f"w{i}" for i in range(8)]))
    assert sum(len(batch) for batch in batches) == 1


def test_dispatch_rejects_missing_event_identity():
    dispatcher = EventDispatcher({"lead.created": lambda ctx, payload: {"ok": True}})
    with pytest.raises(EventRejected):
        dispatcher.dispatch({"id": "x", "organization_id": "org-a", "topic": "lead.created"})


def test_dispatch_rejects_non_object_payload():
    dispatcher = EventDispatcher({"lead.created": lambda ctx, payload: {"ok": True}})
    with pytest.raises(EventRejected):
        dispatcher.dispatch(event(payload=["not", "object"]))


def test_duplicate_handler_registration_is_rejected():
    dispatcher = EventDispatcher({"lead.created": lambda ctx, payload: {}})
    with pytest.raises(ValueError):
        dispatcher.register("lead.created", lambda ctx, payload: {})


def test_outbox_context_idempotency_key_is_stable_and_tenant_scoped():
    seen = []
    dispatcher = EventDispatcher({"lead.created": lambda ctx, payload: seen.append(ctx.idempotency_key) or {}})
    dispatcher.dispatch(event(event_id="same", org="org-a"))
    dispatcher.dispatch(event(event_id="same", org="org-b"))
    assert seen[0] != seen[1]
    assert "org-a" in seen[0] and "org-b" in seen[1]


def test_handler_unavailable_exception_is_explicit():
    dispatcher = EventDispatcher()
    with pytest.raises(HandlerUnavailable):
        dispatcher.dispatch(event(topic="no.handler"))
