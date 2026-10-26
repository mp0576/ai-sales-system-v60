from pathlib import Path
from scripts.verify_staging_acceptance import evaluate_rows


def valid_rows():
    rows = []
    for prefix, names in {
        "rpc_exists:": ["request_exception_replay", "decide_exception_replay", "claim_exception_replay", "finish_exception_replay", "reconcile_expired_exception_replays"],
        "service_role_execute:": ["request_exception_replay", "decide_exception_replay", "claim_exception_replay", "finish_exception_replay", "reconcile_expired_exception_replays"],
        "client_execute_revoked:": ["request_exception_replay", "decide_exception_replay", "claim_exception_replay", "finish_exception_replay", "reconcile_expired_exception_replays"],
        "rls_enabled:": ["exception_replay_requests", "exception_replay_audit", "operational_exceptions"],
        "dispatch_columns:": ["dispatch_worker_id", "dispatch_lease_until", "finished_at", "result_code", "idempotency_key", "replay_number"],
    }.items():
        rows.extend({"check_name": prefix + name, "result": "PASS", "detail": "fixture"} for name in names)
    rows.extend({"check_name": name, "result": "PASS", "detail": "fixture"} for name in (
        "atomic_claim_locking", "expired_lease_reconciliation_only", "claim_rpc_security_definer_search_path"))
    return rows


def test_v38_acceptance_requires_complete_pass_evidence():
    ok, errors = evaluate_rows(valid_rows())
    assert ok and not errors


def test_v38_acceptance_fails_on_any_catalog_or_grant_failure():
    rows = valid_rows()
    rows[0]["result"] = "FAIL"
    ok, errors = evaluate_rows(rows)
    assert not ok
    assert any("returned FAIL" in error for error in errors)


def test_v38_acceptance_fails_on_partial_export_and_duplicate_names():
    rows = valid_rows()[:4]
    ok, errors = evaluate_rows(rows)
    assert not ok
    assert any("missing required check group" in error or "incomplete" in error for error in errors)
    duplicate = valid_rows() + [valid_rows()[0]]
    ok, errors = evaluate_rows(duplicate)
    assert not ok and any("duplicate check" in error for error in errors)


def test_v38_sql_probe_is_select_only_and_covers_privilege_boundaries():
    root = Path(__file__).resolve().parents[1]
    sql = (root / "sql/staging_replay_dispatch_acceptance.sql").read_text().lower()
    assert "has_function_privilege('service_role'" in sql
    assert "has_function_privilege('anon'" in sql
    assert "relrowsecurity" in sql
    assert "for update skip locked" in sql
    assert not any(token in sql for token in ("insert into ", "update public.", "delete from ", "alter table ", "grant ", "revoke "))
