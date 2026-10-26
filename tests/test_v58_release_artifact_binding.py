from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_binding_v58", ROOT / "scripts" / "verify_production_promotion_v58.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

KEY = b"v58-release-binding-test-key-32-bytes"

def signed_report(commit="a" * 40, digest="b" * 64):
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "schema_version": 1, "project_ref": "abcdefghijklmnopqrst", "captured_at": now,
        "organization_a": "org-a", "organization_b": "org-b",
        "checks": {"auth_user_a": True, "auth_user_b": True, "tenant_isolation_a_to_b": True,
                   "tenant_isolation_b_to_a": True, "same_key_replay": True,
                   "concurrent_first_write": True, "stale_version_conflict": True,
                   "migration_0024_applied": True, "live_actions_disabled": True},
        "live_outbound_enabled": False, "live_payments_enabled": False,
        "operator": "staging-operator", "environment": "staging",
        "source_commit": commit, "artifact_sha256": digest,
    }
    return module._gate._verifier._signing.sign_report(report, KEY)

def env():
    return {"STAGING_EVIDENCE_HMAC_KEY": KEY.decode(),
            "LIVE_OUTBOUND_ENABLED": "false", "LIVE_PAYMENTS_ENABLED": "false"}

def test_matching_commit_and_artifact_digest_pass():
    ok, errors = module.evaluate_release(signed_report(), env(), expected_commit="a"*40, artifact_sha256="b"*64)
    assert ok and errors == []

def test_different_commit_blocks():
    ok, errors = module.evaluate_release(signed_report(), env(), expected_commit="c"*40, artifact_sha256="b"*64)
    assert not ok and any("commit does not match" in e for e in errors)

def test_different_artifact_blocks():
    ok, errors = module.evaluate_release(signed_report(), env(), expected_commit="a"*40, artifact_sha256="c"*64)
    assert not ok and any("digest does not match" in e for e in errors)

def test_missing_binding_fields_block():
    envelope = signed_report()
    report = dict(envelope["report"])
    report.pop("source_commit")
    report.pop("artifact_sha256")
    envelope = module._gate._verifier._signing.sign_report(report, KEY)
    ok, errors = module.evaluate_release(envelope, env(), expected_commit="a"*40, artifact_sha256="b"*64)
    assert not ok and any("source_commit" in e for e in errors) and any("artifact_sha256" in e for e in errors)

def test_unsigned_or_tampered_evidence_still_blocks():
    envelope = signed_report()
    envelope["report"]["source_commit"] = "c"*40
    ok, errors = module.evaluate_release(envelope, env(), expected_commit="c"*40, artifact_sha256="b"*64)
    assert not ok and any("signature" in e for e in errors)

def test_missing_expected_artifact_or_commit_blocks():
    ok, errors = module.evaluate_release(signed_report(), env())
    assert not ok and any("expected source commit is required" in e for e in errors)
    assert any("release artifact SHA-256 is required" in e for e in errors)
