"""Policy-first event dispatcher for durable outbox messages.

The dispatcher deliberately contains no provider-specific business logic. Registered
handlers must be idempotent at the provider boundary and must not trust payload-supplied
tenant identifiers over the tenant recorded on the durable outbox row.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
import re

class EventRejected(PermissionError):
    """Event cannot be safely dispatched."""

class HandlerUnavailable(RuntimeError):
    """No handler is registered for an event topic."""

@dataclass(frozen=True)
class EventContext:
    organization_id: str
    outbox_id: str
    event_id: str
    topic: str
    attempt: int
    idempotency_key: str

@dataclass(frozen=True)
class DispatchResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

Handler = Callable[[EventContext, dict[str, Any]], dict[str, Any] | DispatchResult]

class EventDispatcher:
    def __init__(self, handlers: dict[str, Handler] | None = None):
        self._handlers = dict(handlers or {})

    def register(self, topic: str, handler: Handler) -> None:
        topic = topic.strip().lower()
        if not topic or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,119}", topic):
            raise ValueError("invalid event topic")
        if topic in self._handlers:
            raise ValueError("handler already registered for topic")
        self._handlers[topic] = handler

    def dispatch(self, row: dict[str, Any]) -> DispatchResult:
        required = ("id", "event_id", "organization_id", "topic")
        if any(not row.get(k) for k in required):
            raise EventRejected("outbox row is missing required identity fields")
        topic = str(row["topic"]).strip().lower()
        handler = self._handlers.get(topic)
        if handler is None:
            raise HandlerUnavailable(f"no handler registered for topic: {topic}")
        payload = row.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise EventRejected("event payload must be an object")
        # A payload may carry a tenant field for diagnostics, but may never switch context.
        payload_org = payload.get("organization_id")
        if payload_org is not None and str(payload_org) != str(row["organization_id"]):
            raise EventRejected("payload tenant does not match durable event tenant")
        ctx = EventContext(
            organization_id=str(row["organization_id"]),
            outbox_id=str(row["id"]), event_id=str(row["event_id"]), topic=topic,
            attempt=max(1, int(row.get("attempts") or 1)),
            idempotency_key=f"outbox:{row['organization_id']}:{row['event_id']}:{topic}",
        )
        result = handler(ctx, payload)
        if isinstance(result, DispatchResult):
            return result
        if not isinstance(result, dict):
            raise TypeError("event handler must return a dict or DispatchResult")
        return DispatchResult("SUCCEEDED", result)
