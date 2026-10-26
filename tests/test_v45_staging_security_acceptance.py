import json
from pathlib import Path
from datetime import datetime, timezone

from scripts.staging_security_acceptance import validate_concurrency_report, build_report
from scripts.staging_tenant_isolation import Check


def valid_concurrency_report():
    return {
        "schema_version": 1,
        "probe": "staging_concurrent_replay_claim",
        "environment": "staging",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "organization_id": "123e4567-e89b-42d3-a456-426614174000",
        "replay_request_id": "123e4567-e89b-42d3-a456-426614174001",
        "decision": "PASS",
        "external_provider_called": False,
        "claim_invariant": {"decision": "PASS", "winners": 1, "attempts": 2},
        "workers": [{"worker": "worker-a", "claimed": True}, {"worker": "worker-b", "claimed": False}],
        "cleanup": [{"worker": "worker-a", "status": "RECONCILIATION_REQUIRED"}],
    }


def test_v45_accepts_only_strict_concurrency_evidence():
    assert validate_concurrency_report(valid_concurrency_report()) == (True, "concurrency_report_validated")
    report = valid_concurrency_report()
    report["external_provider_called"] = True
    assert validate_concurrency_report(report)[0] is False


def test_v45_rejects_zero_or_two_winners_and_missing_cleanup():
    report = valid_concurrency_report()
    report["claim_invariant"]["winners"] = 2
    assert validate_concurrency_report(report)[0] is False
    report = valid_concurrency_report()
    report["cleanup"] = []
    assert validate_concurrency_report(report)[0] is False


def test_v45_acceptance_defaults_to_no_go_without_concurrency_evidence(monkeypatch):
    import scripts.staging_security_acceptance as module
    monkeypatch.setattr(module, "run_checks", lambda env: [Check("tenant", True, "ok")])
    report = build_report({"APP_ENV": "staging"}, None)
    assert report["decision"] == "NO_GO"
    assert report["concurrency"]["decision"] == "BLOCKED"


def test_v45_report_does_not_embed_concurrency_report_contents(tmp_path, monkeypatch):
    import scripts.staging_security_acceptance as module
    monkeypatch.setattr(module, "run_checks", lambda env: [Check("tenant", True, "ok")])
    source = tmp_path / "concurrency.json"
    source.write_text(json.dumps(valid_concurrency_report()), encoding="utf-8")
    report = build_report({"APP_ENV": "staging"}, source)
    assert report["concurrency"]["decision"] == "PASS"
    assert "workers" not in report["concurrency"]
    assert len(report["concurrency"]["evidence_sha256"]) == 64


def test_v46_rejects_stale_or_timezone_naive_evidence():
    from datetime import timedelta
    report = valid_concurrency_report()
    report["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat().replace("+00:00", "Z")
    assert validate_concurrency_report(report) == (False, "evidence_timestamp_out_of_window")
    report = valid_concurrency_report()
    report["observed_at"] = "2026-10-15T10:00:00"
    assert validate_concurrency_report(report) == (False, "timestamp_missing_timezone")


def test_v46_rejects_invalid_fixture_ids_duplicate_workers_and_cleanup_errors():
    report = valid_concurrency_report()
    report["replay_request_id"] = "not-a-uuid"
    assert validate_concurrency_report(report) == (False, "fixture_identity_invalid")
    report = valid_concurrency_report()
    report["workers"][1]["worker"] = "worker-a"
    assert validate_concurrency_report(report) == (False, "worker_identity_invalid")
    report = valid_concurrency_report()
    report["cleanup"][0]["status"] = "DONE"
    assert validate_concurrency_report(report) == (False, "cleanup_incomplete")
