import pytest
from app.orchestrator.runtime import EventDispatcher, EventRejected, HandlerUnavailable, DispatchResult
from app.workers.durable_service import DurableWorkerConfig, DurableWorkerService

BASE = {"id":"ob-1", "event_id":"ev-1", "organization_id":"org-a", "topic":"lead.created",
        "payload":{"lead_id":"lead-1"}, "attempts":1}

def test_dispatcher_passes_durable_tenant_and_stable_idempotency():
    seen = {}
    d = EventDispatcher({"lead.created": lambda ctx, payload: seen.update(ctx=ctx, payload=payload) or {"ok":True}})
    result = d.dispatch(BASE)
    assert result.status == "SUCCEEDED"
    assert seen["ctx"].organization_id == "org-a"
    assert seen["ctx"].idempotency_key == "outbox:org-a:ev-1:lead.created"

def test_dispatcher_rejects_tenant_spoofing():
    d = EventDispatcher({"lead.created": lambda ctx, payload: {"ok":True}})
    row = {**BASE, "payload":{"organization_id":"org-b"}}
    with pytest.raises(EventRejected): d.dispatch(row)

def test_dispatcher_rejects_incomplete_identity():
    with pytest.raises(EventRejected): EventDispatcher().dispatch({"id":"x"})

def test_dispatcher_rejects_unknown_topic():
    with pytest.raises(HandlerUnavailable): EventDispatcher().dispatch(BASE)

def test_dispatcher_rejects_non_object_payload():
    d = EventDispatcher({"lead.created": lambda ctx, payload: {}})
    with pytest.raises(EventRejected): d.dispatch({**BASE,"payload":[]})

def test_duplicate_handler_registration_is_rejected():
    d=EventDispatcher({"lead.created": lambda c,p: {}})
    with pytest.raises(ValueError): d.register("lead.created", lambda c,p: {})

def test_worker_completes_successful_event():
    class Repo:
        def claim_outbox(self, **kwargs): return [BASE]
        def finish_outbox(self, **kwargs): self.finish=kwargs; return {"status":"DONE"}
    repo=Repo(); d=EventDispatcher({"lead.created": lambda c,p: {"handled":p["lead_id"]}})
    svc=DurableWorkerService(repo,d,config=DurableWorkerConfig(worker_id="w-1"))
    assert svc.run_once()=={"claimed":1,"succeeded":1,"retrying":0,"failed":0,"lease_rejected":0}
    assert repo.finish["succeeded"] is True and repo.finish["organization_id"]=="org-a"

def test_worker_retries_unexpected_provider_error_with_backoff():
    class Repo:
        def claim_outbox(self, **kwargs): return [BASE]
        def finish_outbox(self, **kwargs): self.finish=kwargs; return {"status":"PENDING"}
    repo=Repo(); d=EventDispatcher({"lead.created": lambda c,p: (_ for _ in ()).throw(TimeoutError("secret body"))})
    svc=DurableWorkerService(repo,d,config=DurableWorkerConfig(worker_id="w-1"))
    result=svc.run_once()
    assert result["retrying"]==1
    assert repo.finish["retry_delay_seconds"]==5
    assert "secret body" not in repo.finish["error"]

def test_worker_permanent_error_does_not_leak_details():
    class Repo:
        def claim_outbox(self, **kwargs): return [BASE]
        def finish_outbox(self, **kwargs): self.finish=kwargs; return {"status":"PENDING"}
    repo=Repo(); d=EventDispatcher({"lead.created": lambda c,p: DispatchResult("BLOCKED",error="private details")})
    svc=DurableWorkerService(repo,d,config=DurableWorkerConfig(worker_id="w-1"))
    result=svc.run_once()
    assert result["failed"]==1
    assert repo.finish["permanent"] is True
    assert "private details" not in repo.finish["error"]

def test_worker_handles_stale_lease_rejection():
    class Repo:
        def claim_outbox(self, **kwargs): return [BASE]
        def finish_outbox(self, **kwargs): raise RuntimeError("lease no longer owned")
    svc=DurableWorkerService(Repo(),EventDispatcher({"lead.created": lambda c,p: {}}),config=DurableWorkerConfig(worker_id="w-1"))
    result=svc.run_once()
    assert result["lease_rejected"]==1

def test_worker_requires_nonempty_worker_id():
    with pytest.raises(ValueError): DurableWorkerService(object(),EventDispatcher(),config=DurableWorkerConfig(worker_id=" "))
