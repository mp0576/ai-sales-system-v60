import hashlib
import json
from pathlib import Path

from scripts.verify_staging_rehearsal import REQUIRED_CHECKS, evaluate_manifest, verify_evidence_files


def manifest_for(root: Path):
    checks = []
    for name in REQUIRED_CHECKS:
        rel = Path('artifacts') / f'{name}.log'
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f'evidence for {name}\n'.encode()
        path.write_bytes(content)
        checks.append({
            'check_name': name, 'result': 'PASS', 'evidence_ref': rel.as_posix(),
            'evidence_sha256': hashlib.sha256(content).hexdigest(),
            'observed_at': '2026-10-15T09:00:00Z',
        })
    return {'environment': 'staging', 'run_id': 'test-run-043',
            'started_at': '2026-10-15T09:00:00Z', 'checks': checks}


def test_v43_accepts_real_nonempty_files_with_matching_hashes(tmp_path):
    manifest = manifest_for(tmp_path)
    assert evaluate_manifest(manifest)[0]
    assert verify_evidence_files(manifest, tmp_path) == []


def test_v43_rejects_tampered_artifact(tmp_path):
    manifest = manifest_for(tmp_path)
    (tmp_path / manifest['checks'][0]['evidence_ref']).write_text('tampered\n')
    errors = verify_evidence_files(manifest, tmp_path)
    assert any('SHA-256 does not match' in error for error in errors)


def test_v43_rejects_missing_artifact(tmp_path):
    manifest = manifest_for(tmp_path)
    (tmp_path / manifest['checks'][0]['evidence_ref']).unlink()
    errors = verify_evidence_files(manifest, tmp_path)
    assert any('missing or outside' in error for error in errors)


def test_v43_rejects_path_traversal(tmp_path):
    manifest = manifest_for(tmp_path)
    manifest['checks'][0]['evidence_ref'] = '../outside.log'
    errors = verify_evidence_files(manifest, tmp_path)
    assert any('safe relative path' in error for error in errors)


def test_v43_rejects_symlinked_artifact(tmp_path):
    manifest = manifest_for(tmp_path)
    ref = Path(manifest['checks'][0]['evidence_ref'])
    target = tmp_path / 'outside.log'
    target.write_text('evidence\n')
    actual = tmp_path / ref
    actual.unlink()
    actual.symlink_to(target)
    errors = verify_evidence_files(manifest, tmp_path)
    assert any('symlink' in error for error in errors)


def test_v43_rejects_empty_artifact(tmp_path):
    manifest = manifest_for(tmp_path)
    (tmp_path / manifest['checks'][0]['evidence_ref']).write_bytes(b'  \n')
    manifest['checks'][0]['evidence_sha256'] = hashlib.sha256(b'  \n').hexdigest()
    errors = verify_evidence_files(manifest, tmp_path)
    assert any('is empty' in error for error in errors)


def test_v43_report_keeps_artifact_errors_separate_from_schema_errors(tmp_path):
    manifest = manifest_for(tmp_path)
    manifest['checks'][0]['evidence_sha256'] = '0' * 64
    ok, schema_errors, report = evaluate_manifest(manifest)
    assert ok and not schema_errors
    artifact_errors = verify_evidence_files(manifest, tmp_path)
    report['artifact_verification'] = {'checked': True, 'errors': artifact_errors}
    report['errors'] = schema_errors + artifact_errors
    report['decision'] = 'NO-GO' if report['errors'] else 'GO_FOR_MANUAL_REVIEW'
    assert report['decision'] == 'NO-GO'
    assert any('SHA-256 does not match' in error for error in report['errors'])
