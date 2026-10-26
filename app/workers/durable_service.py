"""Glue durable Supabase outbox claiming to the policy-first dispatcher."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from app.orchestrator.runtime import EventDispatcher, EventRejected, HandlerUnavailable
from app.workers.runtime import WorkerRuntime, RetryableError, PermanentError

@dataclass(frozen=True)
class DurableWorkerConfig:
    worker_id: str
    batch_size: int = 10
    lease_seconds: int = 120
    max_attempts: int = 5

class DurableWorkerService:
    def __init__(self, repository: Any, dispatcher: EventDispatcher, *, config: DurableWorkerConfig,
                 worker_runtime: WorkerRuntime | None = None, exception_store: Any | None = None):
        if not config.worker_id.strip():
            raise ValueError("worker_id is required")
        self.repository = repository
        self.dispatcher = dispatcher
        self.config = config
        self.runtime = worker_runtime or WorkerRuntime()
        # Optional durable exception store. It must be a trusted backend repository.
        self.exception_store = exception_store

    def _record_dead_letter(self, row: dict[str, Any], summary: dict[str, Any]) -> None:
        """Best-effort durable exception creation after the outbox failure is committed.

        The exception store uses a tenant/source unique key, so replaying this method
        cannot create duplicate incidents. Never include event payloads or raw errors.
        """
        if self.exception_store is None:
            return
        organization_id = row.get("organization_id")
        outbox_id = row.get("id")
        if not isinstance(organization_id, str) or not organization_id.strip() or not isinstance(outbox_id, str) or not outbox_id.strip():
            summary["exception_errors"] += 1
            return
        try:
            result = self.exception_store.create(
                organization_id=organization_id,
                source_type="outbox",
                source_id=outbox_id,
                code="DEAD_LETTER",
                severity="HIGH",
                summary="Work item exhausted retries or failed permanently; review before replay",
            )
            if isinstance(result, dict) and result.get("exception_id"):
                summary["exceptions_persisted"] += 1
            else:
                summary["exception_errors"] += 1
        except Exception:
            # Exception recording must not turn a committed dead-letter into success.
            summary["exception_errors"] += 1

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        # Avoid writing payloads, credentials or provider response bodies into logs.
        return f"{type(exc).__name__}: event processing failed"[:500]

    def run_once(self) -> dict[str, Any]:
        rows = self.repository.claim_outbox(worker_id=self.config.worker_id,
            batch_size=self.config.batch_size, lease_seconds=self.config.lease_seconds)
        summary = {"claimed": len(rows), "succeeded": 0, "retrying": 0, "failed": 0, "lease_rejected": 0}
        if self.exception_store is not None:
            summary.update({"exceptions_persisted": 0, "exception_errors": 0})
        for row in rows:
            org_id = str(row.get("organization_id") or "")
            outbox_id = str(row.get("id") or "")
            try:
                result = self.dispatcher.dispatch(row)
                if result.status == "RETRY":
                    raise RetryableError(result.error or "handler requested retry")
                if result.status != "SUCCEEDED":
                    raise PermanentError("handler returned non-success status")
                self.repository.finish_outbox(organization_id=org_id, outbox_id=outbox_id,
                    worker_id=self.config.worker_id, succeeded=True)
                summary["succeeded"] += 1
            except (EventRejected, HandlerUnavailable, PermanentError) as exc:
                try:
                    self.repository.finish_outbox(organization_id=org_id, outbox_id=outbox_id,
                        worker_id=self.config.worker_id, succeeded=False, error=self._safe_error(exc),
                        retry_delay_seconds=86400, permanent=True)
                    summary["failed"] += 1
                    self._record_dead_letter(row, summary)
                except Exception:
                    summary["lease_rejected"] += 1
            except Exception as exc:
                try:
                    attempt = max(1, int(row.get("attempts") or 1))
                except (TypeError, ValueError):
                    attempt = self.config.max_attempts
                exhausted = attempt >= self.config.max_attempts
                retry_delay = 86400 if exhausted else self.runtime.backoff(attempt)
                try:
                    self.repository.finish_outbox(organization_id=org_id, outbox_id=outbox_id,
                        worker_id=self.config.worker_id, succeeded=False, error=self._safe_error(exc),
                        retry_delay_seconds=retry_delay, permanent=exhausted)
                    if exhausted:
                        summary["failed"] += 1
                        self._record_dead_letter(row, summary)
                    else:
                        summary["retrying"] += 1
                except Exception:
                    summary["lease_rejected"] += 1
        return summary
