from app.workers.runtime import WorkerRuntime, WorkerConfig, RetryableError, PermanentError
from app.contracts.n8n import N8nCallback, validate_callback

def test_retry_backoff_is_bounded():
    r = WorkerRuntime(WorkerConfig(base_backoff_seconds=2, max_backoff_seconds=5))
    assert [r.backoff(i) for i in (1,2,3,4)] == [2,4,5,5]

def test_retry_then_success():
    calls=[]
    def h(_):
        calls.append(1)
        if len(calls) < 3: raise RetryableError("temporary")
        return {"ok": True}
    sleeps=[]
    result=WorkerRuntime(WorkerConfig(base_backoff_seconds=1), sleep=sleeps.append).run_with_retries(h,{})
    assert result.status == "SUCCEEDED" and result.attempts == 3 and sleeps == [1,2]

def test_retry_budget_dead_letters():
    result=WorkerRuntime(WorkerConfig(max_attempts=2), sleep=lambda _:None).run_with_retries(lambda _: (_ for _ in ()).throw(RetryableError("down")), {})
    assert result.status == "DEAD_LETTER" and result.attempts == 2

def test_permanent_error_does_not_retry():
    result=WorkerRuntime().run_with_retries(lambda _: (_ for _ in ()).throw(PermanentError("bad payload")), {})
    assert result.status == "FAILED" and result.attempts == 1

def test_n8n_callback_contract():
    validate_callback(N8nCallback("j1","org1","SUCCEEDED",{}))
