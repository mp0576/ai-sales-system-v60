import json
import subprocess
import sys
from pathlib import Path
import pytest
from app.pilot.replay_policy import plan_exception_replay

BASE = {"exception_id": "ex-1", "code": "DEAD_LETTER", "status": "OPEN",
        "failure_class": "TRANSIENT_NETWORK", "external_outcome": "NOT_APPLIED",
        "idempotency_key": "original-key-123", "replay_count": 0}

def test_known_transient_with_stable_key_gets_plan_only():
    result = plan_exception_replay(BASE)
    assert result == {"action": "REPLAY_PLAN", "reason_code": "ALLOWLISTED_TRANSIENT_AND_IDEMPOTENT",
                      "execute": False, "preserve_idempotency_key": True, "next_replay_count": 1}

@pytest.mark.parametrize("code", ["PROVIDER_OUTCOME_UNKNOWN", "PAYMENT_RECONCILIATION_REQUIRED", "WEBHOOK_SIGNATURE_INVALID", "HUMAN_APPROVAL_REQUIRED"])
def test_sensitive_codes_require_reconciliation(code):
    assert plan_exception_replay({**BASE, "code": code})["action"] == "RECONCILE"

def test_unknown_outcome_never_replays():
    assert plan_exception_replay({**BASE, "external_outcome": "UNKNOWN"})["action"] == "RECONCILE"

def test_missing_key_and_unallowlisted_failure_hold():
    assert plan_exception_replay({**BASE, "idempotency_key": ""})["reason_code"] == "STABLE_IDEMPOTENCY_KEY_REQUIRED"
    assert plan_exception_replay({**BASE, "failure_class": "PERMANENT"})["action"] == "HOLD"

def test_budget_is_bounded_and_exhaustion_holds():
    assert plan_exception_replay({**BASE, "replay_count": 3})["reason_code"] == "REPLAY_BUDGET_EXHAUSTED"
    with pytest.raises(ValueError): plan_exception_replay(BASE, max_replays=11)

def test_only_open_or_acknowledged_state_can_be_planned():
    assert plan_exception_replay({**BASE, "status": "RESOLVED"})["action"] == "HOLD"

def test_cli_is_read_only_and_outputs_plan(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps([BASE]), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run([sys.executable, str(root / "scripts" / "exception_replay_plan.py"), str(source)], cwd=root, capture_output=True, text=True)
    assert run.returncode == 0
    payload = json.loads(run.stdout)
    assert payload["mode"] == "READ_ONLY_PLAN"
    assert payload["items"][0]["execute"] is False
