from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class N8nJob:
    job_id: str
    organization_id: str
    topic: str
    payload: dict[str, Any]
    idempotency_key: str

@dataclass(frozen=True)
class N8nCallback:
    job_id: str
    organization_id: str
    status: str
    output: dict[str, Any]
    error: str | None = None

ALLOWED_STATUSES = {"SUCCEEDED", "RETRY", "FAILED", "DEAD_LETTER"}

def validate_callback(callback: N8nCallback) -> None:
    if callback.status not in ALLOWED_STATUSES:
        raise ValueError("invalid callback status")
    if not callback.job_id or not callback.organization_id:
        raise ValueError("job_id and organization_id are required")
