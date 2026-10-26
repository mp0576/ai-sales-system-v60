from dataclasses import dataclass, field
from typing import Any

@dataclass
class TenantMemoryRepository:
    """Deterministic repository used by unit tests; mirrors tenant-scoped DB semantics."""
    leads: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def create_lead(self, organization_id: str, lead_id: str, **data: Any) -> dict[str, Any]:
        row = {"id": lead_id, "organization_id": organization_id, **data}
        self.leads[lead_id] = row
        return row

    def get_lead(self, organization_id: str, lead_id: str) -> dict[str, Any] | None:
        row = self.leads.get(lead_id)
        if row is None or row["organization_id"] != organization_id:
            return None
        return row

    def append_event(self, organization_id: str, event_type: str, idempotency_key: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        key = (organization_id, idempotency_key)
        if key in self.events:
            return False, self.events[key]
        row = {"organization_id": organization_id, "type": event_type, "idempotency_key": idempotency_key, "payload": payload}
        self.events[key] = row
        return True, row
