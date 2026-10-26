from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_rpc_contracts import EXPECTED, check_contracts, find_function, normalize_args


def test_argument_parser_normalizes_sql_types_and_defaults():
    assert normalize_args("p_org uuid, p_count integer default 10, p_data jsonb") == ["p_org", "p_count", "p_data"]


def test_function_parser_reads_signature():
    sql = "create or replace function public.demo(p_org uuid, p_key text) returns table(id uuid) language sql as $$ select 1 $$;"
    assert find_function(sql, "demo") == ["p_org", "p_key"]


def test_function_parser_returns_none_for_missing_function():
    assert find_function("select 1;", "demo") is None


def test_expected_rpc_contracts_are_explicit():
    assert len(EXPECTED) == 16
    assert EXPECTED["claim_provider_webhook"][-2:] == ["p_provider_created_at", "p_object_id"]


def test_all_static_rpc_contracts_match_migrations():
    failed = [(name, detail) for name, ok, detail in check_contracts(ROOT) if not ok]
    assert not failed, failed


def test_staging_sql_is_read_only():
    sql = (ROOT / "sql" / "staging_contract_check.sql").read_text().lower()
    assert "select " in sql
    assert "insert into" not in sql and "update " not in sql and "delete from" not in sql


def test_staging_sql_checks_all_privileged_runtime_functions():
    sql = (ROOT / "sql" / "staging_contract_check.sql").read_text()
    for name in ("claim_action_idempotency", "finish_action_idempotency", "claim_provider_webhook",
                 "finish_provider_webhook", "claim_outbox", "finish_outbox", "create_operational_exception",
                 "transition_operational_exception"):
        assert name in sql


def test_rpc_contract_checker_does_not_require_network():
    checks = check_contracts(ROOT)
    assert checks and all(ok for _, ok, _ in checks)


def test_migration_docs_explain_staging_contract_query():
    guide = (ROOT / "sql" / "MIGRATIONS.md").read_text(encoding="utf-8")
    assert "staging_contract_check.sql" in guide


def test_latest_migration_definition_wins_when_rpc_is_replaced():
    sql = """
    create or replace function public.demo(p_org uuid) returns table(id uuid) language sql as $$ select 1 $$;
    create or replace function public.demo(p_org uuid, p_key text) returns table(id uuid) language sql as $$ select 1 $$;
    """
    assert find_function(sql, "demo") == ["p_org", "p_key"]


def test_release_gate_contains_rpc_contract_check():
    from app.release.gate import static_checks
    results = static_checks(ROOT)
    check = next(item for item in results if item.name == "rpc_contracts")
    assert check.passed, check.detail
