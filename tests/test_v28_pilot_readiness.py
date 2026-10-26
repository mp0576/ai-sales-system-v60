from pathlib import Path
from scripts.check_pilot_readiness import check_report

ROOT = Path(__file__).resolve().parents[1]


def test_pilot_readiness_report_is_complete_and_fail_closed():
    ok, missing = check_report(ROOT)
    assert ok, missing


def test_report_blocks_live_traffic_until_remote_evidence_exists():
    report = (ROOT / "PILOT_READINESS_REPORT.md").read_text(encoding="utf-8").lower()
    assert "no-go for live commercial automation" in report
    assert "remote evidence pending" in report
    assert "outbound_enabled=false" in report
    assert "enable_live_payments=false" in report


def test_report_includes_two_tenant_and_provider_timeout_checks():
    report = (ROOT / "PILOT_READINESS_REPORT.md").read_text(encoding="utf-8").lower()
    assert "two organizations" in report
    assert "timeout-after-acceptance" in report
    assert "cross-tenant reads and writes are denied" in report
