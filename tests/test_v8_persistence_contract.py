from pathlib import Path
from app.repositories.in_memory import TenantMemoryRepository

ROOT = Path(__file__).parents[1]


def test_event_idempotency_is_tenant_scoped():
    r = TenantMemoryRepository()
    created, _ = r.append_event("org-a", "LEAD_CREATED", "same", {"x": 1})
    duplicate, original = r.append_event("org-a", "LEAD_CREATED", "same", {"x": 2})
    other_tenant, _ = r.append_event("org-b", "LEAD_CREATED", "same", {"x": 3})
    assert created and not duplicate and other_tenant
    assert original["payload"]["x"] == 1


def test_lead_cannot_cross_tenant_boundary():
    r = TenantMemoryRepository()
    r.create_lead("org-a", "lead-1", state="NEW")
    assert r.get_lead("org-a", "lead-1") is not None
    assert r.get_lead("org-b", "lead-1") is None


def test_migrations_contain_rls_and_atomic_outbox_claim():
    rls = (ROOT / "sql/migrations/0002_rls.sql").read_text()
    claim = (ROOT / "sql/migrations/0003_outbox_claim.sql").read_text()
    assert "enable row level security" in rls.lower()
    assert "auth.uid()" in rls
    assert "for update skip locked" in claim.lower()
