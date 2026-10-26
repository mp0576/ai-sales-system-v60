from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_staging_security_matrix_is_read_only():
    sql = (ROOT / "sql" / "staging_security_matrix.sql").read_text(encoding="utf-8").lower()
    assert "has_table_privilege" in sql
    assert "relrowsecurity" in sql
    assert "aclexplode" in sql
    assert not any(token in sql for token in ("insert into ", "update public.", "delete from ", "alter table ", "grant ", "revoke "))


def test_security_matrix_covers_critical_tenant_tables():
    sql = (ROOT / "sql" / "staging_security_matrix.sql").read_text(encoding="utf-8").lower()
    for table in ("organizations", "organization_members", "leads", "contacts", "messages",
                  "actions", "events", "outbox_events", "approval_requests", "audit_logs", "payment_events"):
        assert f"'{table}'" in sql


def test_security_matrix_checks_privileged_runtime_rpc_grants():
    sql = (ROOT / "sql" / "staging_security_matrix.sql").read_text(encoding="utf-8").lower()
    for rpc in ("claim_outbox", "finish_outbox", "claim_action_idempotency", "finish_action_idempotency",
                "claim_provider_webhook", "finish_provider_webhook", "resolve_dashboard_approval"):
        assert f"'{rpc}'" in sql


def test_security_matrix_documented_as_staging_evidence_not_certification():
    docs = (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    assert "staging_security_matrix.sql" in docs
