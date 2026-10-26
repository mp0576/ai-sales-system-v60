"""Tenant-scoped, privacy-preserving pilot monitoring and alert rules."""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime, timezone
from typing import Iterable, Mapping
from app.pilot.metrics import calculate_pilot_metrics


def _event_date(event: Mapping) -> str | None:
    value = event.get("timestamp") or event.get("created_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None  # Naive timestamps are ambiguous; fail closed.
        return parsed.astimezone(timezone.utc).date().isoformat()
    except (ValueError, OverflowError):
        return None


def build_daily_report(events: Iterable[Mapping], organization_id: str, report_date: str,
                       *, max_unknown_outcomes: int = 0, max_failed_actions: int = 0,
                       max_human_intervention_rate: float = 0.5) -> dict:
    """Build a minimal report for one tenant/day; never emit contact payloads."""
    if not organization_id or not organization_id.strip():
        raise ValueError("organization_id is required")
    try:
        date.fromisoformat(report_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("report_date must be YYYY-MM-DD") from exc
    if max_unknown_outcomes < 0 or max_failed_actions < 0 or not 0 <= max_human_intervention_rate <= 1:
        raise ValueError("alert thresholds are out of range")

    selected = []
    ignored_other_tenant = 0
    ignored_bad_timestamp = 0
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if event.get("organization_id") != organization_id:
            ignored_other_tenant += 1
            continue
        event_date = _event_date(event)
        if event_date is None:
            ignored_bad_timestamp += 1
            continue
        if event_date == report_date:
            # Only metrics-relevant fields are passed downstream; PII is dropped.
            selected.append({"type": str(event.get("type", ""))})

    metrics = calculate_pilot_metrics(selected)
    alerts = []
    if metrics["provider_unknown_outcomes"] > max_unknown_outcomes:
        alerts.append({"severity": "critical", "code": "PROVIDER_OUTCOME_UNKNOWN", "count": metrics["provider_unknown_outcomes"]})
    if metrics["failed_actions"] > max_failed_actions:
        alerts.append({"severity": "high", "code": "ACTION_FAILED", "count": metrics["failed_actions"]})
    if metrics["human_intervention_rate"] > max_human_intervention_rate:
        alerts.append({"severity": "warning", "code": "HUMAN_INTERVENTION_RATE_HIGH", "rate": metrics["human_intervention_rate"]})
    return {
        "report_date": report_date,
        "organization_id": organization_id,
        "event_count": len(selected),
        "metrics": metrics,
        "alerts": alerts,
        "data_quality": {
            "events_ignored_other_tenant": ignored_other_tenant,
            "events_ignored_missing_or_invalid_timezone_timestamp": ignored_bad_timestamp,
        },
        "privacy": "PII omitted; aggregate operational metrics only",
        "live_system_verified": False,
    }
