import json

from app.dashboard.supabase_leads import SupabaseLeadRepository
from app.repositories.real_estate_leads import LeadConflict


class ErrorResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.content = json.dumps(payload).encode()
    def json(self):
        return json.loads(self.content)


def test_postgrest_unique_violation_is_normalized_to_lead_conflict(monkeypatch):
    class Client:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, *args, **kwargs):
            return ErrorResponse(409, {"code": "23505", "message": "idempotency key reused"})
    import app.dashboard.supabase_leads as module
    monkeypatch.setattr(module.httpx, "Client", Client)
    repo = SupabaseLeadRepository("user-token", url="https://project.supabase.co", anon_key="anon")
    try:
        repo.save_snapshot(organization_id="org", lead_id="lead", state="NEW", payload={},
                           idempotency_key="idempotency-001")
    except LeadConflict:
        pass
    else:
        raise AssertionError("Expected SQL unique violation to become LeadConflict")


def test_postgrest_serialization_failure_is_normalized(monkeypatch):
    class Client:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, *args, **kwargs):
            return ErrorResponse(400, {"code": "40001", "message": "version conflict"})
    import app.dashboard.supabase_leads as module
    monkeypatch.setattr(module.httpx, "Client", Client)
    repo = SupabaseLeadRepository("user-token", url="https://project.supabase.co", anon_key="anon")
    try:
        repo.save_snapshot(organization_id="org", lead_id="lead", state="NEW", payload={},
                           idempotency_key="idempotency-002", expected_version=1)
    except LeadConflict:
        pass
    else:
        raise AssertionError("Expected SQL serialization failure to become LeadConflict")


def test_v52_migration_serializes_first_write_races():
    from pathlib import Path
    migration = Path("sql/migrations/0024_operational_lead_concurrency.sql").read_text().lower()
    assert "pg_advisory_xact_lock" in migration
    assert "':idem:'" in migration
    assert "':lead:'" in migration
    assert migration.index("':idem:'") < migration.index("':lead:'")
    assert "auth.uid()" in migration
    assert "grant execute on function public.save_operational_lead_snapshot" in migration
    assert " to authenticated" in migration


def test_release_gate_requires_v52_migration():
    from pathlib import Path
    gate = Path("app/release/gate.py").read_text()
    assert '"0024_operational_lead_concurrency.sql"' in gate
