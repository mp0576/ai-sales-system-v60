from datetime import datetime, timezone
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("promotion_v57", ROOT / "scripts" / "verify_production_promotion_v57.py")
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)

KEY = b"v57-test-key-with-at-least-32-bytes!!"

def good_envelope():
    sign = module._verifier._signing
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "schema_version": 1, "project_ref": "abcdefghijklmnopqrst",
        "captured_at": now, "organization_a": "org-a", "organization_b": "org-b",
        "checks": {
            "auth_user_a": True, "auth_user_b": True, "tenant_isolation_a_to_b": True,
            "tenant_isolation_b_to_a": True, "same_key_replay": True,
            "concurrent_first_write": True, "stale_version_conflict": True,
            "migration_0024_applied": True, "live_actions_disabled": True
        },
        "live_outbound_enabled": False, "live_payments_enabled": False,
        "operator": "staging-operator", "environment": "staging"
    }
    return sign.sign_report(report, KEY)

def env(**kwargs):
    base = {"STAGING_EVIDENCE_HMAC_KEY": KEY.decode(), "LIVE_OUTBOUND_ENABLED": "false", "LIVE_PAYMENTS_ENABLED": "0"}
    base.update(kwargs)
    return base

def test_valid_signed_staging_evidence_only_eligible_for_manual_review():
    ok, errors = module.evaluate_promotion(good_envelope(), env())
    assert ok and not errors

def test_missing_signing_key_blocks():
    ok, errors = module.evaluate_promotion(good_envelope(), {"LIVE_OUTBOUND_ENABLED":"0","LIVE_PAYMENTS_ENABLED":"0"})
    assert not ok and any("HMAC_KEY" in x for x in errors)

def test_live_outbound_enabled_blocks():
    ok, errors = module.evaluate_promotion(good_envelope(), env(LIVE_OUTBOUND_ENABLED="true"))
    assert not ok and any("LIVE_OUTBOUND_ENABLED" in x for x in errors)

def test_live_payments_enabled_blocks():
    ok, errors = module.evaluate_promotion(good_envelope(), env(LIVE_PAYMENTS_ENABLED="true"))
    assert not ok and any("LIVE_PAYMENTS_ENABLED" in x for x in errors)

def test_tampered_envelope_blocks():
    envelope = good_envelope()
    envelope["report"]["organization_a"] = "tampered"
    ok, errors = module.evaluate_promotion(envelope, env())
    assert not ok and any("signature" in x for x in errors)

def test_wrong_environment_blocks():
    envelope = good_envelope()
    envelope = module._verifier._signing.sign_report({**envelope["report"], "environment":"production"}, KEY)
    ok, errors = module.evaluate_promotion(envelope, env())
    assert not ok and any("environment" in x for x in errors)
