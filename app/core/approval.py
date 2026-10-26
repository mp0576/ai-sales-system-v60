from dataclasses import dataclass
from enum import Enum

class ApprovalState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

@dataclass
class Approval:
    id: str
    action_id: str
    organization_id: str
    state: ApprovalState = ApprovalState.PENDING
    resolution: str | None = None

    def resolve(self, approved: bool, reason: str) -> None:
        if self.state is not ApprovalState.PENDING:
            raise RuntimeError("approval already resolved")
        self.state = ApprovalState.APPROVED if approved else ApprovalState.REJECTED
        self.resolution = reason

    def can_resume(self) -> bool:
        return self.state is ApprovalState.APPROVED
