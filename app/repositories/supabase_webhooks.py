"""Durable webhook inbox helpers for provider callbacks.

The inbox deduplicates provider event IDs and arbitrates concurrent processing.
Webhook handlers must verify provider signatures before calling this repository.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from app.repositories.supabase_runtime import SupabaseRuntimeRepository, RuntimeRepositoryError


class WebhookInboxError(RuntimeError):
    pass


def is_newer_provider_update(incoming: datetime, current: datetime | None) -> bool:
    """Only apply object-state updates newer than the last applied provider timestamp.

    Normalize naive timestamps as UTC to avoid machine-local timezone assumptions.
    This helper is for state snapshots, not for discarding distinct financial ledger events.
    """
    if current is None:
        return True
    if incoming.tzinfo is None:
        incoming = incoming.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return incoming.astimezone(timezone.utc) > current.astimezone(timezone.utc)


class SupabaseWebhookInbox:
    def __init__(self, repository: SupabaseRuntimeRepository | None = None):
        self.repository = repository or SupabaseRuntimeRepository()

    def claim(self, *, organization_id: str, provider: str, event_id: str, worker_id: str,
              lease_seconds: int = 120, provider_created_at: datetime | None = None,
              object_id: str | None = None) -> dict[str, Any]:
        if not organization_id.strip() or not provider.strip() or not event_id.strip() or not worker_id.strip():
            raise ValueError("organization_id, provider, event_id and worker_id are required")
        if len(provider) > 40 or len(event_id) > 250 or len(worker_id) > 200:
            raise ValueError("webhook identity field exceeds maximum length")
        if not 15 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 15 and 3600")
        created_at = provider_created_at
        if created_at is not None:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            created_at = created_at.astimezone(timezone.utc)
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/claim_provider_webhook", body={
                "p_organization_id": organization_id,
                "p_provider": provider,
                "p_event_id": event_id,
                "p_worker_id": worker_id,
                "p_lease_seconds": lease_seconds,
                "p_provider_created_at": created_at.isoformat() if created_at else None,
                "p_object_id": object_id,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise WebhookInboxError("Could not claim provider webhook") from exc
        if not isinstance(rows, list) or not rows or rows[0].get("decision") not in {"PROCESS", "BUSY", "REPLAY"}:
            raise WebhookInboxError("Webhook claim returned an invalid decision")
        return rows[0]

    def finish(self, *, organization_id: str, provider: str, event_id: str, worker_id: str,
               succeeded: bool, error_code: str | None = None) -> dict[str, Any]:
        if not organization_id.strip() or not provider.strip() or not event_id.strip() or not worker_id.strip():
            raise ValueError("organization_id, provider, event_id and worker_id are required")
        # Keep only a short non-sensitive code; never persist webhook payloads or secrets here.
        safe_error = (error_code or "")[:80]
        try:
            rows = self.repository._request("POST", "/rest/v1/rpc/finish_provider_webhook", body={
                "p_organization_id": organization_id,
                "p_provider": provider,
                "p_event_id": event_id,
                "p_worker_id": worker_id,
                "p_succeeded": bool(succeeded),
                "p_error_code": safe_error,
            }, prefer="return=representation")
        except RuntimeRepositoryError as exc:
            raise WebhookInboxError("Could not persist webhook processing result") from exc
        if not isinstance(rows, list) or not rows:
            raise WebhookInboxError("Webhook completion rejected: lease ownership mismatch")
        return rows[0]
