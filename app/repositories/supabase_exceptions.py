"""Durable tenant-scoped operational exception repository.

Only trusted backend code may use this service-role repository. User identity and
membership are checked again by PostgreSQL before a transition is committed.
"""
from __future__ import annotations
from typing import Any
from app.repositories.supabase_runtime import SupabaseRuntimeRepository, RuntimeRepositoryError


class OperationalExceptionStoreError(RuntimeError):
    pass


class SupabaseOperationalExceptionStore:
    def __init__(self, repository: SupabaseRuntimeRepository | None = None):
        self.repository = repository or SupabaseRuntimeRepository()

    @staticmethod
    def _required(value: str, name: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise ValueError(f"{name} is required and must be at most {maximum} characters")
        return value.strip()

    def create(self, *, organization_id: str, source_type: str, source_id: str,
               code: str, severity: str, summary: str) -> dict[str, Any]:
        organization_id = self._required(organization_id, "organization_id", 100)
        source_type = self._required(source_type, "source_type", 60)
        source_id = self._required(source_id, "source_id", 250)
        code = self._required(code, "code", 80)
        summary = self._required(summary, "summary", 300)
        severity = severity.upper().strip() if isinstance(severity, str) else ""
        if severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise ValueError("unsupported exception severity")
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/create_operational_exception", body={
                "p_organization_id": organization_id, "p_source_type": source_type,
                "p_source_id": source_id, "p_code": code, "p_severity": severity,
                "p_summary": summary,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise OperationalExceptionStoreError("Could not persist operational exception") from exc
        if not isinstance(rows, list) or not rows or not rows[0].get("exception_id"):
            raise OperationalExceptionStoreError("Exception creation RPC returned an invalid result")
        return rows[0]

    def transition(self, *, organization_id: str, exception_id: str, actor_user_id: str,
                   action: str, assigned_to: str | None = None, note: str | None = None) -> dict[str, Any]:
        organization_id = self._required(organization_id, "organization_id", 100)
        exception_id = self._required(exception_id, "exception_id", 100)
        actor_user_id = self._required(actor_user_id, "actor_user_id", 100)
        if action not in {"assign", "acknowledge", "resolve", "dismiss"}:
            raise ValueError("unsupported exception action")
        if action == "assign":
            assigned_to = self._required(assigned_to or "", "assigned_to", 100)
        if action in {"resolve", "dismiss"}:
            note = self._required(note or "", "note", 500)
        elif note is not None and len(note) > 500:
            raise ValueError("note exceeds 500 characters")
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/transition_operational_exception", body={
                "p_organization_id": organization_id, "p_exception_id": exception_id,
                "p_actor_user_id": actor_user_id, "p_action": action,
                "p_assigned_to": assigned_to, "p_note": note,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise OperationalExceptionStoreError("Could not transition operational exception") from exc
        if not isinstance(rows, list) or not rows:
            raise OperationalExceptionStoreError("Exception transition returned no result")
        return rows[0]

    def request_replay(self, *, organization_id: str, exception_id: str, actor_user_id: str,
                       replay_number: int, failure_class: str, external_outcome: str,
                       idempotency_key: str, reason: str) -> dict[str, Any]:
        """Persist a bounded replay request; this does not dispatch work."""
        organization_id = self._required(organization_id, "organization_id", 100)
        exception_id = self._required(exception_id, "exception_id", 100)
        actor_user_id = self._required(actor_user_id, "actor_user_id", 100)
        idempotency_key = self._required(idempotency_key, "idempotency_key", 250)
        reason = self._required(reason, "reason", 500)
        if not isinstance(replay_number, int) or isinstance(replay_number, bool) or not 1 <= replay_number <= 10:
            raise ValueError("replay_number must be between 1 and 10")
        if failure_class not in {"TRANSIENT_NETWORK", "RATE_LIMITED", "TEMPORARY_PROVIDER_ERROR"}:
            raise ValueError("failure class is not allowlisted")
        if external_outcome != "NOT_APPLIED":
            raise ValueError("external outcome must be confirmed NOT_APPLIED")
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/request_exception_replay", body={
                "p_organization_id": organization_id, "p_exception_id": exception_id,
                "p_actor_user_id": actor_user_id, "p_replay_number": replay_number,
                "p_failure_class": failure_class, "p_external_outcome": external_outcome,
                "p_idempotency_key": idempotency_key, "p_reason": reason,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise OperationalExceptionStoreError("Could not persist replay request") from exc
        if not isinstance(rows, list) or not rows or not rows[0].get("replay_request_id"):
            raise OperationalExceptionStoreError("Replay request RPC returned an invalid result")
        return rows[0]

    def decide_replay(self, *, organization_id: str, replay_request_id: str, actor_user_id: str,
                      approve: bool, note: str) -> dict[str, Any]:
        """Record a manager decision; approved records still require a separate dispatcher."""
        organization_id = self._required(organization_id, "organization_id", 100)
        replay_request_id = self._required(replay_request_id, "replay_request_id", 100)
        actor_user_id = self._required(actor_user_id, "actor_user_id", 100)
        note = self._required(note, "note", 500)
        if not isinstance(approve, bool):
            raise ValueError("approve must be a boolean")
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/decide_exception_replay", body={
                "p_organization_id": organization_id, "p_replay_request_id": replay_request_id,
                "p_actor_user_id": actor_user_id, "p_approve": approve, "p_note": note,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise OperationalExceptionStoreError("Could not record replay decision") from exc
        if not isinstance(rows, list) or not rows:
            raise OperationalExceptionStoreError("Replay decision RPC returned an invalid result")
        return rows[0]

    def claim_replay_dispatch(self, *, organization_id: str, replay_request_id: str,
                              worker_id: str, lease_seconds: int = 60) -> dict[str, Any] | None:
        """Atomically reserve an approved replay. A missing row means not claimable."""
        organization_id = self._required(organization_id, "organization_id", 100)
        replay_request_id = self._required(replay_request_id, "replay_request_id", 100)
        worker_id = self._required(worker_id, "worker_id", 120)
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 15 <= lease_seconds <= 300:
            raise ValueError("lease_seconds must be between 15 and 300")
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/claim_exception_replay", body={
                "p_organization_id": organization_id, "p_replay_request_id": replay_request_id,
                "p_worker_id": worker_id, "p_lease_seconds": lease_seconds,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise OperationalExceptionStoreError("Could not claim replay dispatch") from exc
        if not isinstance(rows, list):
            raise OperationalExceptionStoreError("Replay claim RPC returned an invalid result")
        return rows[0] if rows else None

    def reconcile_expired_replays(self, *, cutoff_seconds: int = 120) -> int:
        """Move expired dispatch leases to reconciliation; never re-dispatch them.

        This is a mutating maintenance operation and must only be called by a trusted
        staging/operations worker after explicit operator intent.
        """
        if (not isinstance(cutoff_seconds, int) or isinstance(cutoff_seconds, bool)
                or not 30 <= cutoff_seconds <= 86400):
            raise ValueError("cutoff_seconds must be between 30 and 86400")
        try:
            result = self.repository._request("POST", "/rest/v1/rpc/reconcile_expired_exception_replays",
                body={"p_cutoff": f"{cutoff_seconds} seconds"}, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise OperationalExceptionStoreError("Could not reconcile expired replay leases") from exc
        # PostgREST scalar-return functions may be represented as a scalar or a one-row list.
        if isinstance(result, int) and not isinstance(result, bool) and result >= 0:
            return result
        if isinstance(result, list) and len(result) == 1:
            row = result[0]
            if isinstance(row, int) and not isinstance(row, bool) and row >= 0:
                return row
            if isinstance(row, dict):
                value = row.get("reconcile_expired_exception_replays")
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    return value
        raise OperationalExceptionStoreError("Expired replay reconciliation RPC returned an invalid result")

    def finish_replay_dispatch(self, *, organization_id: str, replay_request_id: str,
                               worker_id: str, outcome: str, result_code: str) -> dict[str, Any]:
        organization_id = self._required(organization_id, "organization_id", 100)
        replay_request_id = self._required(replay_request_id, "replay_request_id", 100)
        worker_id = self._required(worker_id, "worker_id", 120)
        result_code = self._required(result_code, "result_code", 80)
        if outcome not in {"SUCCEEDED", "FAILED_DEFINITE", "OUTCOME_UNKNOWN"}:
            raise ValueError("unsupported dispatch outcome")
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/finish_exception_replay", body={
                "p_organization_id": organization_id, "p_replay_request_id": replay_request_id,
                "p_worker_id": worker_id, "p_outcome": outcome, "p_result_code": result_code,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise OperationalExceptionStoreError("Could not finish replay dispatch") from exc
        if not isinstance(rows, list) or not rows:
            raise OperationalExceptionStoreError("Replay finish RPC returned an invalid result")
        return rows[0]
