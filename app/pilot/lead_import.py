"""Safe CSV lead import validation for a controlled pilot.

This module validates input only. It does not persist leads or send messages.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping

REQUIRED_COLUMNS = {
    "organization_id", "external_id", "name", "email", "phone", "source",
    "consent_status", "consent_at",
}
VALID_CONSENT = {"opt_in", "unknown", "opt_out"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class LeadImportRow:
    organization_id: str
    external_id: str
    name: str
    email: str
    phone: str
    source: str
    consent_status: str
    consent_at: str

    @property
    def contactable(self) -> bool:
        return self.consent_status == "opt_in" and bool(self.consent_at)


@dataclass
class ImportReport:
    accepted: list[LeadImportRow] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    non_contactable: list[str] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.accepted)


def _valid_iso_date(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_csv(content: str, expected_organization_id: str) -> ImportReport:
    """Validate UTF-8 CSV text for one tenant; no side effects or network calls."""
    report = ImportReport()
    if not expected_organization_id.strip():
        raise ValueError("expected_organization_id is required")
    try:
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
        headers = {h.strip() for h in (reader.fieldnames or []) if h}
        missing = REQUIRED_COLUMNS - headers
        if missing:
            report.rejected.append({"line": 1, "reason": "missing_columns", "columns": sorted(missing)})
            return report
        seen_external: set[str] = set()
        seen_contact: set[str] = set()
        for line, raw in enumerate(reader, start=2):
            row = {str(k).strip(): (v or "").strip() for k, v in raw.items() if k is not None}
            reason = None
            org = row.get("organization_id", "")
            external_id = row.get("external_id", "")
            email = row.get("email", "").lower()
            phone = row.get("phone", "")
            consent = row.get("consent_status", "").lower()
            consent_at = row.get("consent_at", "")
            if org != expected_organization_id:
                reason = "organization_mismatch"
            elif not external_id or not row.get("name") or not row.get("source"):
                reason = "missing_required_value"
            elif email and not EMAIL_RE.match(email):
                reason = "invalid_email"
            elif consent not in VALID_CONSENT:
                reason = "invalid_consent_status"
            elif consent == "opt_in" and not _valid_iso_date(consent_at):
                reason = "opt_in_requires_valid_consent_timestamp"
            elif external_id in seen_external or (email and f"e:{email}" in seen_contact) or (phone and f"p:{phone}" in seen_contact):
                report.duplicates.append({"line": line, "external_id": external_id, "reason": "duplicate_external_id_or_contact"})
                continue
            if reason:
                report.rejected.append({"line": line, "external_id": external_id, "reason": reason})
                continue
            seen_external.add(external_id)
            if email:
                seen_contact.add(f"e:{email}")
            if phone:
                seen_contact.add(f"p:{phone}")
            item = LeadImportRow(
                organization_id=org, external_id=external_id, name=row["name"],
                email=email, phone=phone, source=row["source"],
                consent_status=consent, consent_at=consent_at,
            )
            report.accepted.append(item)
            if not item.contactable:
                report.non_contactable.append(external_id)
    except csv.Error as exc:
        report.rejected.append({"line": 0, "reason": "csv_parse_error", "detail": str(exc)})
    return report
