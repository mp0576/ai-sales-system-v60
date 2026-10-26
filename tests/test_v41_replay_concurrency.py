"""Deterministic concurrency and crash-window tests for replay dispatch contracts.

These tests exercise the dispatcher with an atomic in-memory store. They do not
replace live PostgreSQL/Supabase staging tests.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

from app.workers.replay_dispatcher import ReplayDispatcher


class AtomicClaimStore:
    def __init__(self):
        self._lock = Lock()
        self.claimed = False
        self.finish = []

    def claim_replay_dispatch(self, **kwargs):
        with self._lock:
            if self.claimed:
                return None
            self.claimed = True
            return {
                "replay_request_id": kwargs["replay_request_id"],
                "exception_id": "exception-1",
                "idempotency_key": "stable-original-key",
                "replay_number": 1,
                "failure_class": "TRANSIENT_NETWORK",
            }

    def finish_replay_dispatch(self, **kwargs):
        with self._lock:
            self.finish.append(dict(kwargs))
        status = {
            "SUCCEEDED": "EXECUTED",
            "FAILED_DEFINITE": "FAILED",
            "OUTCOME_UNKNOWN": "RECONCILIATION_REQUIRED",
        }[kwargs["outcome"]]
        return {"status": status}


def test_v41_two_workers_racing_for_same_request_only_one_calls_executor():
    store = AtomicClaimStore()
    barrier = Barrier(2)
    calls = []
    calls_lock = Lock()

    def executor(command):
        with calls_lock:
            calls.append(command)
        return {"outcome": "SUCCEEDED", "result_code": "OK"}

    def run(worker_id):
        barrier.wait(timeout=3)
        return ReplayDispatcher(store, executor, worker_id=worker_id).dispatch_one(
            organization_id="org-test", replay_request_id="request-1"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ("worker-a", "worker-b")))

    assert len(calls) == 1
    assert calls[0]["idempotency_key"] == "stable-original-key"
    assert sum(result.get("status") == "EXECUTED" for result in results) == 1
    assert len(store.finish) == 1


def test_v41_provider_side_effect_then_timeout_goes_to_reconciliation_not_retry():
    store = AtomicClaimStore()
    side_effects = []

    def provider(command):
        # Model a provider that applied the operation but whose response was lost.
        side_effects.append(command["idempotency_key"])
        raise TimeoutError("sensitive provider response must not leak")

    dispatcher = ReplayDispatcher(store, provider, worker_id="worker-a")
    result = dispatcher.dispatch_one(organization_id="org-test", replay_request_id="request-1")

    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert len(side_effects) == 1
    assert store.finish[-1]["outcome"] == "OUTCOME_UNKNOWN"
    assert "sensitive provider response" not in str(result)

    # A second worker cannot blindly re-dispatch the same already-claimed request.
    second = ReplayDispatcher(store, provider, worker_id="worker-b").dispatch_one(
        organization_id="org-test", replay_request_id="request-1"
    )
    assert second["status"] == "NOT_DISPATCHED"
    assert len(side_effects) == 1


def test_v41_finish_persistence_failure_never_reports_success():
    class BrokenFinishStore(AtomicClaimStore):
        def finish_replay_dispatch(self, **kwargs):
            raise RuntimeError("storage unavailable")

    store = BrokenFinishStore()
    result = ReplayDispatcher(
        store, lambda _: {"outcome": "SUCCEEDED", "result_code": "OK"}, worker_id="worker-a"
    ).dispatch_one(organization_id="org-test", replay_request_id="request-1")
    assert result == {"status": "RECONCILIATION_REQUIRED", "reason_code": "FINISH_PERSISTENCE_FAILED"}
