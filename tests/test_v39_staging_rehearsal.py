from datetime import datetime, timezone
from scripts.verify_staging_rehearsal import REQUIRED_CHECKS, evaluate_manifest


def valid_manifest():
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "environment": "staging", "run_id": "rehearsal-2026-001", "started_at": now,
        "checks": [{"check_name": name, "result": "PASS", "evidence_ref": f"artifacts/{name}.log",
                    "evidence_sha256": "a" * 64, "observed_at": now} for name in REQUIRED_CHECKS],
    }


def test_v39_complete_manifest_is_only_referred_for_manual_review():
    ok, errors, report = evaluate_manifest(valid_manifest())
    assert ok and errors == []
    assert report["decision"] == "GO_FOR_MANUAL_REVIEW"
    assert len(report["limitations"]) >= 3


def test_v39_fails_closed_on_missing_check_and_failed_result():
    data = valid_manifest()
    data["checks"].pop()
    data["checks"][0]["result"] = "FAIL"
    ok, errors, report = evaluate_manifest(data)
    assert not ok and report["decision"] == "NO-GO"
    assert any("missing required check" in e for e in errors)
    assert any("result must be PASS" in e for e in errors)


def test_v39_rejects_duplicate_checks_bad_digest_and_path_traversal():
    data = valid_manifest()
    item = data["checks"][0]
    item["evidence_ref"] = "../secret.txt"
    item["evidence_sha256"] = "not-a-hash"
    data["checks"].append(dict(item))
    ok, errors, _ = evaluate_manifest(data)
    assert not ok
    assert any("parent traversal" in e for e in errors)
    assert any("SHA-256" in e for e in errors)
    assert any("duplicate check" in e for e in errors)


def test_v39_rejects_non_staging_and_non_utc_timestamp():
    data = valid_manifest()
    data["environment"] = "production"
    data["started_at"] = "2026-10-14T12:00:00+01:00"
    ok, errors, _ = evaluate_manifest(data)
    assert not ok
    assert any("environment" in e for e in errors)
    assert any("started_at" in e for e in errors)
