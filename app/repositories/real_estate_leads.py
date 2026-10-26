"""Tenant-scoped SQLite persistence adapter for the real-estate lead pipeline.

This adapter is intended for local development and isolated staging rehearsals.
For hosted production, use the equivalent PostgreSQL migration and a trusted backend
adapter; never expose a database file or service-role credential to clients.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from pathlib import Path
from typing import Any


class LeadRepositoryError(RuntimeError):
    """Base class for safe repository errors."""


class LeadConflict(LeadRepositoryError):
    """The supplied idempotency key or optimistic version conflicts with stored data."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SQLiteLeadRepository:
    """Durable tenant-scoped lead snapshots, idempotency and append-only event history."""

    def __init__(self, database: str | Path):
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 10000")
        return con

    def _initialize(self) -> None:
        with self._connect() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS lead_snapshots (
                    organization_id TEXT NOT NULL,
                    lead_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version >= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (organization_id, lead_id)
                );
                CREATE TABLE IF NOT EXISTS lead_idempotency (
                    organization_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    lead_id TEXT NOT NULL,
                    resulting_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (organization_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS lead_events (
                    event_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    lead_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (organization_id, lead_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS lead_snapshots_queue_idx
                    ON lead_snapshots (organization_id, state, updated_at DESC);
                CREATE INDEX IF NOT EXISTS lead_events_timeline_idx
                    ON lead_events (organization_id, lead_id, created_at, event_id);
            """)

    @staticmethod
    def _validate_id(value: str, label: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 250:
            raise ValueError(f"{label} must be a non-empty string of at most 250 characters")
        return value.strip()

    def save_snapshot(
        self, *, organization_id: str, lead_id: str, state: str,
        payload: dict[str, Any], event_type: str = "LEAD_SNAPSHOT_SAVED",
        idempotency_key: str, expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Persist snapshot and audit event atomically; replaying a key is safe.

        A key replay with identical content returns duplicate=True. Reusing a key with
        different content fails closed. expected_version prevents lost updates.
        """
        org = self._validate_id(organization_id, "organization_id")
        lead = self._validate_id(lead_id, "lead_id")
        idem = self._validate_id(idempotency_key, "idempotency_key")
        state = self._validate_id(state, "state")
        event_type = self._validate_id(event_type, "event_type")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if expected_version is not None and (not isinstance(expected_version, int) or expected_version < 0):
            raise ValueError("expected_version must be a non-negative integer")
        payload_json = _json(payload)
        request_body = {"lead_id": lead, "state": state, "payload": payload, "event_type": event_type,
                        "expected_version": expected_version}
        digest = sha256(_json(request_body).encode("utf-8")).hexdigest()
        now = _now()
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            previous = con.execute(
                "SELECT request_digest, lead_id, resulting_version FROM lead_idempotency WHERE organization_id=? AND idempotency_key=?",
                (org, idem),
            ).fetchone()
            if previous:
                if previous["request_digest"] != digest:
                    raise LeadConflict("idempotency key reused with different request")
                current = con.execute(
                    "SELECT * FROM lead_snapshots WHERE organization_id=? AND lead_id=?", (org, previous["lead_id"])
                ).fetchone()
                con.execute("COMMIT")
                return {"duplicate": True, "version": previous["resulting_version"],
                        "lead": self._snapshot_dict(current) if current else None}

            current = con.execute(
                "SELECT * FROM lead_snapshots WHERE organization_id=? AND lead_id=?", (org, lead)
            ).fetchone()
            actual_version = int(current["version"]) if current else 0
            if expected_version is not None and expected_version != actual_version:
                raise LeadConflict(f"version conflict: expected {expected_version}, found {actual_version}")
            version = actual_version + 1
            created_at = current["created_at"] if current else now
            con.execute("""INSERT INTO lead_snapshots
                (organization_id, lead_id, state, payload_json, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id, lead_id) DO UPDATE SET
                    state=excluded.state, payload_json=excluded.payload_json,
                    version=excluded.version, updated_at=excluded.updated_at""",
                (org, lead, state, payload_json, version, created_at, now))
            event_body = {"organization_id": org, "lead_id": lead, "event_type": event_type,
                          "state": state, "version": version, "payload_digest": sha256(payload_json.encode()).hexdigest(),
                          "idempotency_key_digest": sha256(idem.encode()).hexdigest()}
            event_id = sha256(_json({**event_body, "created_at": now}).encode()).hexdigest()
            con.execute("INSERT INTO lead_events(event_id, organization_id, lead_id, event_type, event_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (event_id, org, lead, event_type, _json(event_body), now))
            con.execute("INSERT INTO lead_idempotency(organization_id, idempotency_key, request_digest, lead_id, resulting_version, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (org, idem, digest, lead, version, now))
            saved = con.execute("SELECT * FROM lead_snapshots WHERE organization_id=? AND lead_id=?", (org, lead)).fetchone()
            con.execute("COMMIT")
            return {"duplicate": False, "version": version, "lead": self._snapshot_dict(saved), "event_id": event_id}
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    @staticmethod
    def _snapshot_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {"organization_id": row["organization_id"], "lead_id": row["lead_id"],
                "state": row["state"], "payload": json.loads(row["payload_json"]),
                "version": row["version"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def get_lead(self, *, organization_id: str, lead_id: str) -> dict[str, Any] | None:
        org = self._validate_id(organization_id, "organization_id")
        lead = self._validate_id(lead_id, "lead_id")
        with self._connect() as con:
            row = con.execute("SELECT * FROM lead_snapshots WHERE organization_id=? AND lead_id=?", (org, lead)).fetchone()
            return self._snapshot_dict(row)

    def list_leads(self, *, organization_id: str, limit: int = 100) -> list[dict[str, Any]]:
        org = self._validate_id(organization_id, "organization_id")
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as con:
            rows = con.execute("SELECT * FROM lead_snapshots WHERE organization_id=? ORDER BY updated_at DESC, lead_id LIMIT ?", (org, limit)).fetchall()
            return [self._snapshot_dict(row) for row in rows]

    def list_events(self, *, organization_id: str, lead_id: str, limit: int = 200) -> list[dict[str, Any]]:
        org = self._validate_id(organization_id, "organization_id")
        lead = self._validate_id(lead_id, "lead_id")
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as con:
            rows = con.execute("SELECT event_id, event_type, event_json, created_at FROM lead_events WHERE organization_id=? AND lead_id=? ORDER BY created_at, event_id LIMIT ?", (org, lead, limit)).fetchall()
            return [{"event_id": r["event_id"], "event_type": r["event_type"],
                     "event": json.loads(r["event_json"]), "created_at": r["created_at"]} for r in rows]
