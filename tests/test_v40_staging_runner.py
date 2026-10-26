import hashlib
import json
from pathlib import Path

from scripts.run_staging_rehearsal import REQUIRED_CHECKS, run_rehearsal


def test_v40_runner_fails_closed_without_live_probe_configuration(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report, code = run_rehearsal(root, tmp_path / "run", {"APP_ENV": "staging"}, "test-run-001")
    assert code == 1
    assert report["decision"] == "NO-GO"
    manifest_path = Path(report["manifest"])
    manifest = json.loads(manifest_path.read_text())
    assert {item["check_name"] for item in manifest["checks"]} == set(REQUIRED_CHECKS)
    assert any(item["result"] == "FAIL" for item in manifest["checks"])
    assert next(item for item in manifest["checks"] if item["check_name"] == "live_actions_disabled")["result"] == "PASS"
    for item in manifest["checks"]:
        artifact = manifest_path.parent / item["evidence_ref"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == item["evidence_sha256"]


def test_v40_production_environment_blocks_all_checks(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report, code = run_rehearsal(root, tmp_path / "run", {"APP_ENV": "production"}, "test-run-002")
    assert code == 1
    assert report["decision"] == "NO-GO"
    manifest = json.loads(Path(report["manifest"]).read_text())
    assert all(item["result"] == "FAIL" for item in manifest["checks"])
    assert all("BLOCKED" in (Path(report["manifest"]).parent / item["evidence_ref"]).read_text()
               for item in manifest["checks"])
