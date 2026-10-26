"""Tenant-scoped exception queue primitives; persistence and notifications are intentionally external."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable, Mapping

# Generic labels only: never copy provider error messages or contact payloads into the queue.
RULES = {
    "PROVIDER_OUTCOME_UNKNOWN": ("critical", "Provider result unknown", "Reconcile with provider before retrying"),
    "ACTION_FAILED": ("high", "Commercial action failed", "Inspect safe error code and retry policy"),
    "WEBHOOK_SIGNATURE_INVALID": ("critical", "Webhook signature rejected", "Check provider configuration; do not process event"),
    "HUMAN_APPROVAL_REQUIRED": ("high", "Human approval required", "Review the pending decision"),
    "PAYMENT_RECONCILIATION_REQUIRED": ("critical", "Payment reconciliation required", "Verify provider and internal ledger before changing state"),
    "DEAD_LETTER": ("high", "Work item dead-lettered", "Inspect redacted diagnostics and decide whether to replay"),
}

MANAGER_ROLES = {"OWNER", "ADMIN", "MANAGER"}
TERMINAL = {"RESOLVED", "DISMISSED"}


def _timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_exception_queue(events: Iterable[Mapping], organization_id: str) -> dict:
    """Create deterministic, tenant-filtered exception items from exported events.

    The caller must persist items with a unique (organization_id, exception_id) key to
    make repeated imports idempotent. This function itself performs no writes.
    """
    if not isinstance(organization_id, str) or not organization_id.strip():
        raise ValueError("organization_id is required")
    items: dict[str, dict] = {}
    ignored_other_tenant = 0
    ignored_invalid = 0
    for event in events:
        if not isinstance(event, Mapping):
            ignored_invalid += 1
            continue
        if event.get("organization_id") != organization_id:
            ignored_other_tenant += 1
            continue
        code = event.get("type")
        rule = RULES.get(code) if isinstance(code, str) else None
        if not rule:
            continue
        source_id = event.get("event_id") or event.get("id")
        timestamp = _timestamp(event.get("timestamp") or event.get("created_at"))
        if not isinstance(source_id, str) or not source_id.strip() or timestamp is None:
            ignored_invalid += 1
            continue
        severity, title, next_step = rule
        digest = sha256(f"{organization_id}\0{source_id}\0{code}".encode()).hexdigest()[:24]
        items.setdefault(digest, {
            "exception_id": digest,
            "organization_id": organization_id,
            "source_event_id": source_id,
            "code": code,
            "severity": severity,
            "title": title,
            "next_step": next_step,
            "occurred_at": timestamp,
            "status": "OPEN",
            "assigned_to": None,
            "resolution_note": None,
        })
    ordered = sorted(items.values(), key=lambda x: ({"critical": 0, "high": 1, "warning": 2}.get(x["severity"], 3), x["occurred_at"], x["exception_id"]))
    return {
        "organization_id": organization_id,
        "items": ordered,
        "counts": {"total": len(ordered), "open": sum(x["status"] == "OPEN" for x in ordered),
                   "critical": sum(x["severity"] == "critical" for x in ordered),
                   "high": sum(x["severity"] == "high" for x in ordered)},
        "data_quality": {"ignored_other_tenant": ignored_other_tenant, "ignored_invalid": ignored_invalid},
        "privacy": "Generic labels only; contact data and raw provider errors omitted",
        "persistence_required_for_deduplication": True,
    }


def transition_exception(item: Mapping, *, organization_id: str, actor_role: str,
                         action: str, actor_id: str, assigned_to: str | None = None,
                         resolution_note: str | None = None) -> dict:
    """Validate a state transition and return a copy; caller must persist atomically."""
    if item.get("organization_id") != organization_id:
        raise PermissionError("cross-organization exception access denied")
    if actor_role not in MANAGER_ROLES:
        raise PermissionError("manager-level role required")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError("actor_id is required")
    status = item.get("status")
    result = dict(item)
    if action == "assign":
        if status in TERMINAL:
            raise ValueError("terminal exceptions cannot be assigned")
        if not isinstance(assigned_to, str) or not assigned_to.strip():
            raise ValueError("assigned_to is required")
        result["assigned_to"] = assigned_to.strip()
    elif action == "acknowledge":
        if status != "OPEN":
            raise ValueError("only open exceptions can be acknowledged")
        result["status"] = "ACKNOWLEDGED"
    elif action == "resolve":
        if status not in {"OPEN", "ACKNOWLEDGED"}:
            raise ValueError("exception is already terminal")
        if not isinstance(resolution_note, str) or not resolution_note.strip():
            raise ValueError("resolution_note is required")
        if len(resolution_note.strip()) > 500:
            raise ValueError("resolution_note must be 500 characters or fewer")
        result["status"] = "RESOLVED"
        result["resolution_note"] = resolution_note.strip()
    elif action == "dismiss":
        if status not in {"OPEN", "ACKNOWLEDGED"}:
            raise ValueError("exception is already terminal")
        if not isinstance(resolution_note, str) or not resolution_note.strip():
            raise ValueError("resolution_note is required")
        result["status"] = "DISMISSED"
        result["resolution_note"] = resolution_note.strip()
    else:
        raise ValueError("unsupported exception action")
    result["last_actor_id"] = actor_id.strip()
    return result
