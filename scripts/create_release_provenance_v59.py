#!/usr/bin/env python3
"""Create a deterministic provenance manifest for the exact release archive."""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def build_manifest(artifact: Path, commit: str, run_id: str, workflow: str, created_at: str) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("commit must be a full 40-character Git SHA")
    if not artifact.is_file(): raise ValueError("artifact must exist and be a file")
    if not run_id.strip() or not workflow.strip(): raise ValueError("run_id and workflow are required")
    return {"schema_version":1,"artifact_name":artifact.name,"artifact_sha256":sha256(artifact),
            "source_commit":commit.lower(),"ci_run_id":run_id,"ci_workflow":workflow,
            "created_at":created_at,"automatic_deployment":False,
            "note":"Provenance metadata only; does not assert staging acceptance or authorize deployment."}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact",required=True,type=Path)
    ap.add_argument("--commit",required=True)
    ap.add_argument("--run-id",required=True)
    ap.add_argument("--workflow",required=True)
    ap.add_argument("--output",required=True,type=Path)
    a=ap.parse_args()
    try:
        data=build_manifest(a.artifact,a.commit,a.run_id,a.workflow,datetime.now(timezone.utc).isoformat())
        a.output.write_text(json.dumps(data,indent=2)+"\\n",encoding="utf-8")
    except (OSError,ValueError) as exc:
        print(f"BLOCKED: {exc}",file=sys.stderr); return 2
    print(json.dumps({"status":"CREATED","artifact_sha256":data["artifact_sha256"],"source_commit":data["source_commit"],"automatic_deployment":False},indent=2))
    return 0
if __name__=="__main__": raise SystemExit(main())
