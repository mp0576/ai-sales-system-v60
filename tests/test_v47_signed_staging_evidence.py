from scripts.sign_staging_evidence import get_key, sign_report, verify_envelope
import copy
import pytest

KEY = b"test-only-key-that-is-at-least-32-bytes-long"

def test_signed_report_verifies():
    envelope = sign_report({"decision": "NO_GO", "checks": ["tenant"]}, KEY)
    assert verify_envelope(envelope, KEY) == (True, "signature_valid_integrity_only")

def test_tampered_report_fails():
    envelope = sign_report({"decision": "PASS"}, KEY)
    envelope["report"]["decision"] = "NO_GO"
    assert verify_envelope(envelope, KEY) == (False, "signature_mismatch")

def test_wrong_key_fails():
    envelope = sign_report({"decision": "PASS"}, KEY)
    assert verify_envelope(envelope, b"different-test-key-that-is-also-long-enough") == (False, "signature_mismatch")

def test_invalid_envelope_fails():
    assert verify_envelope({"schema": "wrong"}, KEY) == (False, "envelope_schema_invalid")

def test_short_key_rejected():
    with pytest.raises(ValueError):
        get_key({"STAGING_EVIDENCE_HMAC_KEY": "too-short"})
