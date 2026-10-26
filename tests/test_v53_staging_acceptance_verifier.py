from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_staging_acceptance_v53.py"
spec = importlib.util.spec_from_file_location("verify_staging_acceptance_v53", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def valid_evidence():
    return {
        "schema_version": 1,
        "project_ref": "abcdefghijklmnopqrst",
        "captured_at": "2026-10-21T12:00:00Z",
        "organization_a": "org-a",
        "organization_b": "org-b",
        "operator": "staging-operator",
        "live_outbound_enabled": False,
        "live_payments_enabled": False,
        "checks": {name: True for name in mod.REQUIRED_CHECKS},
    }


def test_valid_recent_evidence_passes():
    now = datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)
    assert mod.validate_evidence(valid_evidence(), now=now) == []


def test_same_org_is_rejected():
    data = valid_evidence()
    data["organization_b"] = data["organization_a"]
    assert any("different organizations" in e for e in mod.validate_evidence(
        data, now=datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)))


def test_stale_evidence_is_rejected():
    data = valid_evidence()
    now = datetime(2026, 10, 23, 12, 30, tzinfo=timezone.utc)
    assert any("stale" in e for e in mod.validate_evidence(data, now=now))


def test_missing_concurrency_check_is_rejected():
    data = valid_evidence()
    del data["checks"]["concurrent_first_write"]
    assert any("missing required checks" in e for e in mod.validate_evidence(
        data, now=datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)))


def test_live_payments_must_remain_disabled():
    data = valid_evidence()
    data["live_payments_enabled"] = True
    assert any("live_payments_enabled" in e for e in mod.validate_evidence(
        data, now=datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)))


def test_credentials_must_not_be_in_evidence():
    data = valid_evidence()
    data["access_token"] = "do-not-store"
    assert any("forbidden credential field" in e for e in mod.validate_evidence(
        data, now=datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)))
