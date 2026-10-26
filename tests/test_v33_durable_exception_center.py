from pathlib import Path
import pytest
from app.repositories.supabase_exceptions import (
    SupabaseOperationalExceptionStore, OperationalExceptionStoreError,
)
from app.repositories.supabase_runtime import RuntimeRepositoryError


class FakeRepository:
    def __init__(self, rows=None, error=None):
        self.rows = rows if rows is not None else [{"exception_id": "exc-1", "status": "OPEN", "duplicate": False}]
        self.error = error
        self.calls = []

    def _request(self, method, path, *, params=None, body=None, prefer=None):
        self.calls.append((method, path, body, prefer))
        if self.error:
            raise self.error
        return self.rows


def test_create_calls_tenant_scoped_rpc_and_sanitized_contract():
    repo = FakeRepository()
    result = SupabaseOperationalExceptionStore(repo).create(
        organization_id="org-1", source_type="provider", source_id="event-1",
        code="TIMEOUT_UNKNOWN", severity="critical", summary="Provider result requires reconciliation",
    )
    assert result["exception_id"] == "exc-1"
    method, path, body, prefer = repo.calls[0]
    assert method == "POST" and path.endswith("/create_operational_exception")
    assert body["p_organization_id"] == "org-1" and body["p_severity"] == "CRITICAL"
    assert prefer == "return=representation"


def test_create_rejects_bad_fields_before_network():
    repo = FakeRepository()
    store = SupabaseOperationalExceptionStore(repo)
    with pytest.raises(ValueError):
        store.create(organization_id="", source_type="provider", source_id="1", code="X", severity="LOW", summary="x")
    with pytest.raises(ValueError):
        store.create(organization_id="o", source_type="provider", source_id="1", code="X", severity="P0", summary="x")
    assert repo.calls == []


def test_create_requires_valid_rpc_result():
    store = SupabaseOperationalExceptionStore(FakeRepository(rows=[]))
    with pytest.raises(OperationalExceptionStoreError):
        store.create(organization_id="o", source_type="provider", source_id="1", code="X", severity="LOW", summary="x")


def test_transition_requires_note_for_terminal_actions():
    repo = FakeRepository(rows=[{"exception_id": "exc-1", "status": "RESOLVED", "assigned_to": None}])
    store = SupabaseOperationalExceptionStore(repo)
    with pytest.raises(ValueError):
        store.transition(organization_id="o", exception_id="e", actor_user_id="u", action="resolve")
    assert repo.calls == []


def test_transition_passes_actor_and_action_to_sql_membership_guard():
    repo = FakeRepository(rows=[{"exception_id": "exc-1", "status": "ACKNOWLEDGED", "assigned_to": None}])
    result = SupabaseOperationalExceptionStore(repo).transition(
        organization_id="org-1", exception_id="exc-1", actor_user_id="user-1", action="acknowledge")
    assert result["status"] == "ACKNOWLEDGED"
    body = repo.calls[0][2]
    assert body["p_actor_user_id"] == "user-1" and body["p_organization_id"] == "org-1"


def test_transition_requires_assignee_and_valid_action():
    repo = FakeRepository()
    store = SupabaseOperationalExceptionStore(repo)
    with pytest.raises(ValueError):
        store.transition(organization_id="o", exception_id="e", actor_user_id="u", action="assign")
    with pytest.raises(ValueError):
        store.transition(organization_id="o", exception_id="e", actor_user_id="u", action="retry")
    assert repo.calls == []


def test_database_errors_are_wrapped_without_provider_or_sql_details():
    repo = FakeRepository(error=RuntimeRepositoryError("HTTP 403 sensitive detail"))
    with pytest.raises(OperationalExceptionStoreError) as error:
        SupabaseOperationalExceptionStore(repo).create(
            organization_id="o", source_type="provider", source_id="1", code="X", severity="LOW", summary="safe summary")
    assert "sensitive detail" not in str(error.value)


def test_migration_has_tenant_uniqueness_locking_audit_and_role_checks():
    root = Path(__file__).resolve().parents[1]
    sql = (root / "sql/migrations/0019_durable_exception_center.sql").read_text().lower()
    for token in ("unique (organization_id, source_type, source_id)", "for update",
                  "organization_members", "operational_exception_audit", "security definer",
                  "revoke all on function public.transition_operational_exception"):
        assert token in sql


def test_rpc_contracts_include_exception_operations():
    from scripts.check_rpc_contracts import check_contracts
    checks = {name: passed for name, passed, _ in check_contracts(Path(__file__).resolve().parents[1])}
    assert checks["rpc_signature_create_operational_exception"]
    assert checks["rpc_signature_transition_operational_exception"]
    assert checks["rpc_privilege_create_operational_exception"]
    assert checks["rpc_privilege_transition_operational_exception"]
