from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock

import pytest

from app.repositories.supabase_runtime import RuntimeRepositoryError
from app.repositories.supabase_webhooks import (
    SupabaseWebhookInbox, WebhookInboxError, is_newer_provider_update,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeWebhookRepository:
    """Thread-safe RPC model for contract tests; not a PostgreSQL substitute."""
    def __init__(self):
        self.lock = Lock()
        self.rows = {}
        self.calls = []

    def _request(self, method, path, *, params=None, body=None, prefer=None):
        with self.lock:
            self.calls.append((method, path, body))
            key = (body["p_organization_id"], body["p_provider"], body["p_event_id"])
            row = self.rows.get(key)
            if path.endswith("claim_provider_webhook"):
                if row and row["status"] == "PROCESSED":
                    return [{"decision": "REPLAY"}]
                if row and row["status"] == "IN_PROGRESS":
                    return [{"decision": "BUSY"}]
                if row:
                    row.update(status="IN_PROGRESS", worker=body["p_worker_id"], attempts=row["attempts"] + 1)
                else:
                    row = {"status": "IN_PROGRESS", "worker": body["p_worker_id"], "attempts": 1}
                    self.rows[key] = row
                return [{"decision": "PROCESS"}]
            if path.endswith("finish_provider_webhook"):
                if not row or row["status"] != "IN_PROGRESS" or row["worker"] != body["p_worker_id"]:
                    raise RuntimeRepositoryError("lease mismatch")
                row["status"] = "PROCESSED" if body["p_succeeded"] else "RETRYABLE"
                return [{"status": row["status"]}]
            raise AssertionError(path)


def test_webhook_claim_is_tenant_scoped_and_validates_fields():
    repo = FakeWebhookRepository(); inbox = SupabaseWebhookInbox(repo)
    with pytest.raises(ValueError):
        inbox.claim(organization_id="", provider="stripe", event_id="evt_1", worker_id="w1")
    a = inbox.claim(organization_id="org-a", provider="stripe", event_id="evt_1", worker_id="w1")
    b = inbox.claim(organization_id="org-b", provider="stripe", event_id="evt_1", worker_id="w2")
    assert a["decision"] == b["decision"] == "PROCESS"
    assert len(repo.rows) == 2


def test_duplicate_processed_webhook_replays_without_processing_again():
    repo = FakeWebhookRepository(); inbox = SupabaseWebhookInbox(repo)
    claim = inbox.claim(organization_id="org-a", provider="stripe", event_id="evt_1", worker_id="w1")
    assert claim["decision"] == "PROCESS"
    inbox.finish(organization_id="org-a", provider="stripe", event_id="evt_1", worker_id="w1", succeeded=True)
    replay = inbox.claim(organization_id="org-a", provider="stripe", event_id="evt_1", worker_id="w2")
    assert replay["decision"] == "REPLAY"


def test_concurrent_duplicate_claim_has_one_owner_in_thread_safe_model():
    repo = FakeWebhookRepository(); inbox = SupabaseWebhookInbox(repo)
    def claim(worker):
        return inbox.claim(organization_id="org-a", provider="stripe", event_id="evt_race", worker_id=worker)["decision"]
    with ThreadPoolExecutor(max_workers=12) as pool:
        decisions = list(pool.map(claim, [f"w{i}" for i in range(12)]))
    assert decisions.count("PROCESS") == 1
    assert decisions.count("BUSY") == 11


def test_retryable_webhook_can_be_reclaimed_after_failure():
    repo = FakeWebhookRepository(); inbox = SupabaseWebhookInbox(repo)
    inbox.claim(organization_id="org-a", provider="stripe", event_id="evt_retry", worker_id="w1")
    inbox.finish(organization_id="org-a", provider="stripe", event_id="evt_retry", worker_id="w1", succeeded=False, error_code="TEMPORARY")
    retried = inbox.claim(organization_id="org-a", provider="stripe", event_id="evt_retry", worker_id="w2")
    assert retried["decision"] == "PROCESS"


def test_finish_requires_original_lease_owner():
    repo = FakeWebhookRepository(); inbox = SupabaseWebhookInbox(repo)
    inbox.claim(organization_id="org-a", provider="stripe", event_id="evt_lease", worker_id="w1")
    with pytest.raises(WebhookInboxError):
        inbox.finish(organization_id="org-a", provider="stripe", event_id="evt_lease", worker_id="w2", succeeded=True)


def test_out_of_order_state_snapshots_are_not_applied_but_distinct_events_are_not_collapsed():
    current = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    older = current - timedelta(minutes=5)
    newer = current + timedelta(minutes=5)
    assert not is_newer_provider_update(older, current)
    assert is_newer_provider_update(newer, current)
    assert is_newer_provider_update(older, None)


def test_webhook_migration_is_locked_tenant_scoped_and_server_only():
    sql = (ROOT / "sql/migrations/0018_provider_webhook_inbox.sql").read_text().lower()
    assert "unique (organization_id, provider, event_id)" in sql
    assert "for update" in sql
    assert "enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_release_gate_requires_v23_migration():
    from app.release.gate import static_checks
    checks = static_checks(ROOT)
    assert all(c.passed for c in checks), [(c.name, c.detail) for c in checks if not c.passed]
