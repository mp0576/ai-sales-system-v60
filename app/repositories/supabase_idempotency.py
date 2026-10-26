"""Durable idempotency arbitration for side effects across API/worker processes.

The database claim is atomic, but provider I/O is deliberately outside a DB transaction.
Providers should receive the same idempotency key to protect the ambiguous-timeout window.
"""
from __future__ import annotations
import os
from typing import Callable
from app.integrations.base import ProviderResult
from app.repositories.supabase_runtime import SupabaseRuntimeRepository, RuntimeRepositoryError


class IdempotencyStoreError(RuntimeError):
    pass


class SupabaseIdempotencyStore:
    def __init__(self, repository: SupabaseRuntimeRepository | None = None, *, lease_seconds: int = 120):
        self.repository = repository or SupabaseRuntimeRepository()
        if not 15 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 15 and 3600")
        self.lease_seconds = lease_seconds

    @staticmethod
    def _result(data: dict) -> ProviderResult:
        return ProviderResult(
            ok=bool(data.get("ok")), provider=str(data.get("provider") or "unknown"),
            external_id=data.get("external_id"), status=str(data.get("status") or "UNKNOWN"),
            data=data.get("data") if isinstance(data.get("data"), dict) else {},
            retryable=bool(data.get("retryable")), error=data.get("error"),
        )

    def execute_once(self, *, organization_id: str, action_type: str, idempotency_key: str,
                     worker_id: str, call: Callable[[], ProviderResult]) -> ProviderResult:
        if not organization_id.strip() or not worker_id.strip() or not idempotency_key.strip():
            raise ValueError("organization_id, worker_id and idempotency_key are required")
        if action_type not in {"message", "email", "calendar", "checkout"}:
            raise ValueError("unsupported action_type")
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/claim_action_idempotency", body={
                "p_organization_id": organization_id, "p_action_type": action_type,
                "p_idempotency_key": idempotency_key, "p_worker_id": worker_id,
                "p_lease_seconds": self.lease_seconds,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise IdempotencyStoreError("Could not claim durable idempotency key") from exc
        if not isinstance(rows, list) or not rows:
            raise IdempotencyStoreError("Idempotency claim returned no decision")
        claim = rows[0]
        decision = claim.get("decision")
        if decision == "REPLAY":
            result = claim.get("result")
            if not isinstance(result, dict):
                raise IdempotencyStoreError("Completed idempotency record has no result")
            return self._result(result)
        if decision == "BUSY":
            return ProviderResult(False, action_type, status="IN_PROGRESS", retryable=True,
                                  error="An equivalent action is already in progress")
        if decision != "EXECUTE":
            raise IdempotencyStoreError("Unrecognized idempotency decision")
        try:
            result = call()
            if not isinstance(result, ProviderResult):
                raise TypeError("provider call must return ProviderResult")
        except Exception:
            # Leave the lease to expire rather than guessing whether an external side effect
            # happened before the exception. A provider-side idempotency key is essential.
            raise
        payload = {"ok": result.ok, "provider": result.provider, "external_id": result.external_id,
                   "status": result.status, "data": result.data, "retryable": result.retryable,
                   "error": result.error}
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/finish_action_idempotency", body={
                "p_organization_id": organization_id, "p_action_type": action_type,
                "p_idempotency_key": idempotency_key, "p_worker_id": worker_id,
                "p_result": payload, "p_retryable": result.retryable,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            # Do not return success if durable recording failed; a retry will be arbitrated
            # after lease expiry and protected by the provider's own idempotency key.
            raise IdempotencyStoreError("Provider returned, but durable result recording failed") from exc
        if not isinstance(rows, list) or not rows:
            raise IdempotencyStoreError("Idempotency completion rejected: lease ownership mismatch")
        return result
