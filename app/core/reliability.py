from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from time import time
from typing import Dict, Optional

class ActionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"

class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0

    def delay(self, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        return min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt - 1)))

class IdempotencyStore:
    """Small in-memory reference implementation; production uses a DB unique key."""
    def __init__(self) -> None:
        self._values: Dict[str, object] = {}

    def get(self, key: str) -> Optional[object]:
        return self._values.get(key)

    def put_if_absent(self, key: str, value: object) -> tuple[bool, object]:
        if key in self._values:
            return False, self._values[key]
        self._values[key] = value
        return True, value

@dataclass
class Lease:
    execution_id: str
    locked_at: float
    lease_seconds: float = 120.0

    @property
    def expired(self) -> bool:
        return time() >= self.locked_at + self.lease_seconds

class TaskLeaseManager:
    def __init__(self) -> None:
        self._leases: Dict[str, Lease] = {}

    def acquire(self, task_id: str, execution_id: str, lease_seconds: float = 120.0) -> bool:
        current = self._leases.get(task_id)
        if current and not current.expired:
            return current.execution_id == execution_id
        self._leases[task_id] = Lease(execution_id, time(), lease_seconds)
        return True

    def release(self, task_id: str, execution_id: str) -> bool:
        current = self._leases.get(task_id)
        if not current or current.execution_id != execution_id:
            return False
        del self._leases[task_id]
        return True

class WebhookInbox:
    """Deduplicates provider events and ignores stale versions when supplied."""
    def __init__(self) -> None:
        self._processed: set[str] = set()
        self._latest_version: Dict[str, int] = {}

    def accept(self, event_id: str, aggregate_id: str, version: int | None = None) -> bool:
        if event_id in self._processed:
            return False
        if version is not None:
            latest = self._latest_version.get(aggregate_id, -1)
            if version < latest:
                self._processed.add(event_id)
                return False
            self._latest_version[aggregate_id] = version
        self._processed.add(event_id)
        return True
