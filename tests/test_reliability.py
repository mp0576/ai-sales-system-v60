import pytest
from app.core.reliability import IdempotencyStore, RetryPolicy, TaskLeaseManager, WebhookInbox
from app.core.approval import Approval, ApprovalState
from app.core.cost_control import CostBudget

def test_idempotency_returns_original_result():
    s=IdempotencyStore(); assert s.put_if_absent("k", {"ok":1})[0]
    created, value=s.put_if_absent("k", {"ok":2})
    assert not created and value == {"ok":1}

def test_retry_backoff_is_bounded():
    p=RetryPolicy(max_attempts=4, base_delay_seconds=2, max_delay_seconds=5)
    assert [p.delay(i) for i in range(1,5)] == [2,4,5,5]

def test_lease_blocks_concurrent_worker():
    m=TaskLeaseManager(); assert m.acquire("t","a"); assert not m.acquire("t","b"); assert m.release("t","b") is False; assert m.release("t","a")

def test_duplicate_webhook_is_ignored():
    w=WebhookInbox(); assert w.accept("e1","p1"); assert not w.accept("e1","p1")

def test_stale_webhook_is_ignored():
    w=WebhookInbox(); assert w.accept("e2","p1",2); assert not w.accept("e1","p1",1); assert w.accept("e3","p1",3)

def test_approval_resume_only_after_approval():
    a=Approval("a","act","org"); assert not a.can_resume(); a.resolve(True,"approved"); assert a.state is ApprovalState.APPROVED and a.can_resume()

def test_approval_cannot_be_resolved_twice():
    a=Approval("a","act","org"); a.resolve(False,"no");
    with pytest.raises(RuntimeError): a.resolve(True,"yes")

def test_cost_states():
    b=CostBudget(100); assert b.state(79)=="NORMAL"; assert b.state(80)=="WARNING"; assert b.state(90)=="THROTTLE"; assert b.state(100)=="HARD_STOP"
