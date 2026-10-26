import ast
from pathlib import Path

from scripts.staging_concurrent_replay_claim import evaluate_claim_results


def test_v44_concurrency_probe_passes_only_exactly_one_winner():
    assert evaluate_claim_results([{"id": "r"}, None])["decision"] == "PASS"
    assert evaluate_claim_results([None, {"id": "r"}])["decision"] == "PASS"
    assert evaluate_claim_results([None, None])["decision"] == "FAIL"
    assert evaluate_claim_results([{"id": "r"}, {"id": "r"}])["decision"] == "FAIL"
    assert evaluate_claim_results([{"id": "r"}])["decision"] == "FAIL"


def test_v44_probe_requires_explicit_opt_in_and_staging_fixture():
    source = (Path(__file__).resolve().parents[1] / "scripts/staging_concurrent_replay_claim.py").read_text()
    assert '"--execute"' in source
    assert '"--confirm-disposable-fixture"' in source
    assert 'env.get("APP_ENV", "").strip().lower() != "staging"' in source
    assert '"OUTCOME_UNKNOWN"' in source
    assert 'external_provider_called' in source


def test_v44_probe_has_no_provider_executor_or_live_action_call():
    source = (Path(__file__).resolve().parents[1] / "scripts/staging_concurrent_replay_claim.py").read_text().lower()
    assert "replaydispatcher(" not in source
    assert "dispatch_one(" not in source
    assert "external_provider_called\": false" in source
