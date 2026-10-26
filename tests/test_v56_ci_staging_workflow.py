from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v56_workflow_has_static_and_manual_staging_jobs():
    workflow = (ROOT / ".github/workflows/staging-acceptance-v56.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "static-quality:" in workflow
    assert "live-staging-readonly:" in workflow
    assert "needs: static-quality" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow


def test_v56_workflow_uses_environment_secrets_not_inline_credentials():
    workflow = (ROOT / ".github/workflows/staging-acceptance-v56.yml").read_text()
    for name in (
        "STAGING_API_BASE_URL", "STAGING_ORG_A", "STAGING_ORG_B",
        "STAGING_USER_A_TOKEN", "STAGING_USER_B_TOKEN",
        "STAGING_EXISTING_LEAD_A", "STAGING_EXISTING_LEAD_B",
    ):
        assert f"secrets.{name}" in workflow
    assert "service_role" not in workflow.lower()
    assert "upload-artifact@v4" in workflow
    assert "retention-days: 14" in workflow


def test_v56_docs_warn_live_staging_is_not_certification():
    docs = (ROOT / "CI_STAGING_ACCEPTANCE_V56.md").read_text()
    assert "not a full staging certification" in docs
    assert "Do not use service-role keys" in docs
