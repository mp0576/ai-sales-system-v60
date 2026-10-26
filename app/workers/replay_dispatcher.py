"""Approved replay dispatcher with atomic reservation and fail-closed outcomes.

The injected executor must use the supplied original idempotency key with the provider.
External delivery is at-least-once across process crashes; provider idempotency is required.
"""
from __future__ import annotations
from typing import Any, Callable

from app.repositories.supabase_exceptions import OperationalExceptionStoreError


class ReplayDispatcher:
    def __init__(self, store: Any, executor: Callable[[dict[str, Any]], Any], *, worker_id: str,
                 lease_seconds: int = 60):
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id.strip()) > 120:
            raise ValueError("worker_id is required")
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 15 <= lease_seconds <= 300:
            raise ValueError("lease_seconds must be between 15 and 300")
        if not callable(executor):
            raise ValueError("executor callback is required")
        self.store, self.executor = store, executor
        self.worker_id, self.lease_seconds = worker_id.strip(), lease_seconds

    def dispatch_one(self, *, organization_id: str, replay_request_id: str) -> dict[str, Any]:
        """Claim and dispatch one approved replay. Does not log payloads or raw provider errors."""
        try:
            claim = self.store.claim_replay_dispatch(
                organization_id=organization_id, replay_request_id=replay_request_id,
                worker_id=self.worker_id, lease_seconds=self.lease_seconds)
        except OperationalExceptionStoreError:
            return {"status": "NOT_DISPATCHED", "reason_code": "CLAIM_FAILED"}
        if not claim:
            return {"status": "NOT_DISPATCHED", "reason_code": "NOT_APPROVED_OR_ALREADY_CLAIMED"}
        # The executor receives only identifiers and the original idempotency key, not raw DB rows.
        command = {"organization_id": organization_id, "exception_id": claim["exception_id"],
                   "replay_request_id": claim["replay_request_id"], "replay_number": claim["replay_number"],
                   "failure_class": claim["failure_class"], "idempotency_key": claim["idempotency_key"]}
        try:
            result = self.executor(command)
            if not isinstance(result, dict) or result.get("outcome") not in {"SUCCEEDED", "FAILED_DEFINITE", "OUTCOME_UNKNOWN"}:
                outcome, code = "OUTCOME_UNKNOWN", "EXECUTOR_RESULT_INVALID"
            else:
                outcome = result["outcome"]
                code = result.get("result_code", "DISPATCH_COMPLETED")
                if not isinstance(code, str) or not code.strip() or len(code.strip()) > 80:
                    outcome, code = "OUTCOME_UNKNOWN", "EXECUTOR_RESULT_INVALID"
        except Exception:
            # A thrown exception cannot prove that the external operation was not applied.
            outcome, code = "OUTCOME_UNKNOWN", "EXECUTOR_OUTCOME_UNKNOWN"
        try:
            finished = self.store.finish_replay_dispatch(organization_id=organization_id,
                replay_request_id=replay_request_id, worker_id=self.worker_id,
                outcome=outcome, result_code=code)
        except Exception:
            # Do not retry in-process: provider may already have applied the operation.
            # Store errors are deliberately redacted; never leak driver/provider details.
            return {"status": "RECONCILIATION_REQUIRED", "reason_code": "FINISH_PERSISTENCE_FAILED"}
        return {"status": finished.get("status", "RECONCILIATION_REQUIRED"), "reason_code": code}
