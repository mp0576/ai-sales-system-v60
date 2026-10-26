"""Durable public demo-request intake for the real-estate sales offer.

This is a lead-capture component, not a payment processor or outbound messaging system.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class IntakeError(ValueError):
    pass


class PublicDemoRequestRepository:
    STATUSES = {"NEW", "CONTACTED", "QUALIFIED", "WON", "LOST"}

    def __init__(self, database_path: str | None = None):
        self.database_path = database_path or os.getenv(
            "PUBLIC_INTAKE_DATABASE_PATH", "data/public_demo_requests.sqlite3"
        )
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.database_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self):
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS public_demo_requests (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    company TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    team_size TEXT NOT NULL,
                    monthly_leads TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    consent INTEGER NOT NULL CHECK(consent IN (0,1)),
                    status TEXT NOT NULL DEFAULT 'NEW',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demo_requests_email_created ON public_demo_requests(email, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demo_requests_status_created ON public_demo_requests(status, created_at)")

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["consent"] = bool(item["consent"])
        return item

    def create(self, data: dict[str, Any], idempotency_key: str) -> tuple[dict[str, Any], bool]:
        if not idempotency_key or len(idempotency_key) < 8 or len(idempotency_key) > 250:
            raise IntakeError("A valid Idempotency-Key is required")
        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        company = str(data.get("company", "")).strip()
        if len(name) < 2 or len(name) > 120:
            raise IntakeError("Name must contain 2–120 characters")
        if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
            raise IntakeError("A valid email address is required")
        if len(company) < 2 or len(company) > 160:
            raise IntakeError("Company must contain 2–160 characters")
        if data.get("consent") is not True:
            raise IntakeError("Consent is required to process the demo request")
        if str(data.get("website", "")).strip():
            raise IntakeError("Request rejected")
        team_size = str(data.get("team_size", ""))
        monthly_leads = str(data.get("monthly_leads", ""))
        if team_size not in {"1-3", "4-10", "11-25", "26+"}:
            raise IntakeError("Choose a valid team size")
        if monthly_leads not in {"0-20", "21-100", "101-300", "300+"}:
            raise IntakeError("Choose a valid monthly lead volume")
        phone = str(data.get("phone", "")).strip()[:40]
        notes = str(data.get("notes", "")).strip()
        if len(notes) > 2000:
            raise IntakeError("Notes must be at most 2000 characters")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            existing = conn.execute("SELECT * FROM public_demo_requests WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                return self._public(existing), True
            since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            recent = conn.execute(
                "SELECT COUNT(*) FROM public_demo_requests WHERE email=? AND created_at>=?", (email, since)
            ).fetchone()[0]
            if recent >= 5:
                raise IntakeError("Too many requests for this email. Please try again later.")
            request_id = "demo_" + uuid.uuid4().hex
            conn.execute("""
                INSERT INTO public_demo_requests
                (id,idempotency_key,name,email,company,phone,team_size,monthly_leads,notes,consent,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,1,'NEW',?,?)
            """, (request_id,idempotency_key,name,email,company,phone,team_size,monthly_leads,notes,now,now))
            row = conn.execute("SELECT * FROM public_demo_requests WHERE id=?", (request_id,)).fetchone()
            return self._public(row), False

    def list_requests(self, status: str = "ALL", limit: int = 100) -> list[dict[str, Any]]:
        if status not in self.STATUSES | {"ALL"}:
            raise IntakeError("Invalid status")
        if not 1 <= limit <= 250:
            raise IntakeError("Limit must be between 1 and 250")
        with self._connect() as conn:
            if status == "ALL":
                rows = conn.execute("SELECT * FROM public_demo_requests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM public_demo_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status,limit)).fetchall()
            return [self._public(row) for row in rows]

    def update_status(self, request_id: str, status: str) -> dict[str, Any]:
        if status not in self.STATUSES:
            raise IntakeError("Invalid status")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute("UPDATE public_demo_requests SET status=?, updated_at=? WHERE id=?", (status,now,request_id))
            if cur.rowcount != 1:
                raise KeyError(request_id)
            return self._public(conn.execute("SELECT * FROM public_demo_requests WHERE id=?", (request_id,)).fetchone())
