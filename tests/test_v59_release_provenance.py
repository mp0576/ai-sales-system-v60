from pathlib import Path
import importlib.util
import hashlib

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_release_provenance_v59.py"
spec = importlib.util.spec_from_file_location("release_provenance_v59", SCRIPT)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def test_manifest_binds_exact_artifact(tmp_path):
    artifact=tmp_path/"release.zip"; artifact.write_bytes(b"release bytes")
    m=mod.build_manifest(artifact,"a"*40,"12345","release.yml","2026-10-22T08:00:00+00:00")
    assert m["artifact_sha256"] == hashlib.sha256(b"release bytes").hexdigest()
    assert m["source_commit"] == "a"*40
    assert m["automatic_deployment"] is False

def test_rejects_short_commit(tmp_path):
    f=tmp_path/"x"; f.write_text("x")
    try: mod.build_manifest(f,"abc","1","wf","2026-10-22T08:00:00Z")
    except ValueError as e: assert "40-character" in str(e)
    else: assert False, "invalid commit accepted"

def test_rejects_missing_artifact(tmp_path):
    try: mod.build_manifest(tmp_path/"missing","a"*40,"1","wf","2026-10-22T08:00:00Z")
    except ValueError as e: assert "exist" in str(e)
    else: assert False, "missing artifact accepted"
