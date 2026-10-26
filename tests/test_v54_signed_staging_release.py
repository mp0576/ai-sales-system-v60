from datetime import datetime, timezone
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_staging_release_v54", ROOT / "scripts" / "verify_staging_release_v54.py")
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

KEY = b"v54-test-only-key-with-at-least-32-bytes"
NOW = datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)

def valid_report():
    return {
        "schema_version": 1,
        "project_ref": "abcdefghijklmnopqrst",
        "captured_at": "2026-10-21T12:00:00Z",
        "organization_a": "org-a", "organization_b": "org-b",
        "operator": "staging-operator",
        "live_outbound_enabled": False, "live_payments_enabled": False,
        "checks": {name: True for name in mod._acceptance.REQUIRED_CHECKS},
    }

def signed(report=None):
    return mod._signing.sign_report(valid_report() if report is None else report, KEY)

def test_signed_valid_evidence_is_accepted():
    ok, errors, _ = mod.evaluate_envelope(signed(), KEY, now=NOW)
    assert ok and errors == []

def test_unsigned_payload_is_blocked():
    ok, errors, _ = mod.evaluate_envelope(valid_report(), KEY, now=NOW)
    assert not ok and "signature" in errors[0]

def test_tampered_signed_evidence_is_blocked():
    envelope = signed()
    envelope["report"]["organization_b"] = "org-a"
    ok, errors, _ = mod.evaluate_envelope(envelope, KEY, now=NOW)
    assert not ok and "signature_mismatch" in errors[0]

def test_valid_signature_does_not_bypass_failed_policy_check():
    report = valid_report()
    report["checks"]["tenant_isolation_a_to_b"] = False
    ok, errors, _ = mod.evaluate_envelope(signed(report), KEY, now=NOW)
    assert not ok and any("checks must all be literal true" in e for e in errors)

def test_stale_signed_evidence_is_blocked():
    report = valid_report()
    report["captured_at"] = "2026-10-19T12:00:00Z"
    ok, errors, _ = mod.evaluate_envelope(signed(report), KEY, now=NOW)
    assert not ok and any("stale" in e for e in errors)

def test_live_payments_enabled_is_blocked_even_when_signed():
    report = valid_report()
    report["live_payments_enabled"] = True
    ok, errors, _ = mod.evaluate_envelope(signed(report), KEY, now=NOW)
    assert not ok and any("live_payments_enabled" in e for e in errors)

def test_wrong_key_blocks_envelope():
    ok, errors, _ = mod.evaluate_envelope(signed(), b"another-test-key-with-at-least-32-bytes", now=NOW)
    assert not ok and "signature_mismatch" in errors[0]
