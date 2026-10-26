"""Fail-closed policy for planning exception replays; never executes external actions."""
from __future__ import annotations

from typing import Mapping

SENSITIVE_CODES = {
    "PROVIDER_OUTCOME_UNKNOWN",
    "PAYMENT_RECONCILIATION_REQUIRED",
    "WEBHOOK_SIGNATURE_INVALID",
    "HUMAN_APPROVAL_REQUIRED",
}
REPLAYABLE_FAILURE_CLASSES = {"TRANSIENT_NETWORK", "RATE_LIMITED", "TEMPORARY_PROVIDER_ERROR"}


def plan_exception_replay(item: Mapping, *, max_replays: int = 3) -> dict:
    """Return REPLAY/RECONCILE/APPROVAL_REQUIRED/HOLD with generic reason codes.

    Automatic replay requires a known-not-applied external outcome, an allowlisted
    transient failure class, a stable existing idempotency key, and a bounded budget.
    This is a plan only: callers must separately enforce tenant authorization and
    persist/audit any approved transition before dispatch.
    """
    if not isinstance(max_replays, int) or isinstance(max_replays, bool) or not 1 <= max_replays <= 10:
        raise ValueError("max_replays must be an integer from 1 to 10")
    code = str(item.get("code", ""))
    if code in SENSITIVE_CODES or item.get("external_outcome") == "UNKNOWN":
        action, reason = "RECONCILE", "EXTERNAL_OUTCOME_MUST_BE_VERIFIED"
    elif item.get("requires_human_approval") is True:
        action, reason = "APPROVAL_REQUIRED", "HUMAN_APPROVAL_REQUIRED"
    else:
        attempts = item.get("replay_count", 0)
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
            action, reason = "HOLD", "INVALID_REPLAY_COUNT"
        elif attempts >= max_replays:
            action, reason = "HOLD", "REPLAY_BUDGET_EXHAUSTED"
        elif item.get("failure_class") not in REPLAYABLE_FAILURE_CLASSES:
            action, reason = "HOLD", "FAILURE_CLASS_NOT_ALLOWLISTED"
        elif item.get("external_outcome") != "NOT_APPLIED":
            action, reason = "HOLD", "OUTCOME_NOT_CONFIRMED_NOT_APPLIED"
        elif not isinstance(item.get("idempotency_key"), str) or not item["idempotency_key"].strip():
            action, reason = "HOLD", "STABLE_IDEMPOTENCY_KEY_REQUIRED"
        elif item.get("status") not in {"OPEN", "ACKNOWLEDGED"}:
            action, reason = "HOLD", "EXCEPTION_NOT_REPLAYABLE_IN_CURRENT_STATE"
        else:
            action, reason = "REPLAY_PLAN", "ALLOWLISTED_TRANSIENT_AND_IDEMPOTENT"
    return {"action": action, "reason_code": reason, "execute": False,
            "preserve_idempotency_key": action == "REPLAY_PLAN",
            "next_replay_count": item.get("replay_count", 0) + 1 if action == "REPLAY_PLAN" else None}
