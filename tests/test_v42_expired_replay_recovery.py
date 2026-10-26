from pathlib import Path

import pytest

from app.repositories.supabase_exceptions import SupabaseOperationalExceptionStore, OperationalExceptionStoreError


class FakeRuntime:
    def __init__(self, result=2, error=False):
        self.result, self.error, self.calls = result, error, []

    def _request(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body, prefer))
        if self.error:
            from app.repositories.supabase_runtime import RuntimeRepositoryError
            raise RuntimeRepositoryError("sensitive detail")
        return self.result


def test_reconcile_expired_leases_calls_only_reconciliation_rpc_and_returns_count():
    runtime = FakeRuntime(3)
    store = SupabaseOperationalExceptionStore(runtime)
    assert store.reconcile_expired_replays(cutoff_seconds=180) == 3
    method, path, body, prefer = runtime.calls[0]
    assert method == "POST"
    assert path.endswith("/rpc/reconcile_expired_exception_replays")
    assert body == {"p_cutoff": "180 seconds"}
    assert prefer == "return=representation"


@pytest.mark.parametrize("result", [0, [{"reconcile_expired_exception_replays": 4}], [5]])
def test_reconcile_expired_leases_accepts_postgrest_scalar_shapes(result):
    assert SupabaseOperationalExceptionStore(FakeRuntime(result)).reconcile_expired_replays() in (0, 4, 5)


@pytest.mark.parametrize("value", [True, False, 29, 86401, 1.5, "120", None])
def test_reconcile_expired_leases_rejects_unsafe_cutoffs(value):
    with pytest.raises(ValueError):
        SupabaseOperationalExceptionStore(FakeRuntime()).reconcile_expired_replays(cutoff_seconds=value)


def test_reconcile_expired_leases_redacts_remote_errors():
    with pytest.raises(OperationalExceptionStoreError, match="Could not reconcile expired replay leases") as err:
        SupabaseOperationalExceptionStore(FakeRuntime(error=True)).reconcile_expired_replays()
    assert "sensitive detail" not in str(err.value)


def test_v42_sql_reconciles_stale_dispatches_without_requeueing_and_is_service_role_only():
    root = Path(__file__).resolve().parents[1]
    sql = (root / "sql/migrations/0021_controlled_replay_dispatch.sql").read_text().lower()
    start = sql.index("create or replace function public.reconcile_expired_exception_replays")
    end = sql.index("revoke all on function public.claim_exception_replay", start)
    body = sql[start:end]
    assert "status='dispatching'" in body
    assert "status='reconciliation_required'" in body
    assert "dispatch_lease_until < now()-p_cutoff" in body
    assert "insert into public.exception_replay_audit" in body
    assert "update public.exception_replay_requests" in body
    assert "status='approved'" not in body  # no transition back to queue
    assert "revoke all on function public.reconcile_expired_exception_replays(interval) from public, anon, authenticated" in sql
    assert "grant execute on function public.reconcile_expired_exception_replays(interval) to service_role" in sql


def test_v42_maintenance_command_is_opt_in_and_staging_only():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts/reconcile_expired_replays.py").read_text().lower()
    assert '"--execute"' in source
    assert 'env != "staging"' in source
    assert "none were re-dispatched" in source
