from scripts.preflight import validate

def test_preflight_accepts_strong_pilot_token():
    assert validate({'DASHBOARD_API_TOKEN':'a'*48,'APP_ENV':'pilot'}) == []

def test_preflight_rejects_missing_or_short_token():
    errors=validate({'DASHBOARD_API_TOKEN':'short'})
    assert any('at least 32 characters' in e for e in errors)

def test_preflight_rejects_production_claim_for_demo_release():
    errors=validate({'DASHBOARD_API_TOKEN':'x'*48,'APP_ENV':'production'})
    assert any('production mode is not supported' in e for e in errors)

def test_preflight_rejects_live_outbound_and_payments():
    errors=validate({'DASHBOARD_API_TOKEN':'x'*48,'ENABLE_LIVE_OUTBOUND':'true','ENABLE_LIVE_PAYMENTS':'1'})
    assert any('Live outbound' in e for e in errors)
    assert any('Live payment' in e for e in errors)
