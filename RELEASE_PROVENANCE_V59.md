# v59 — CI-generated release provenance

The `release-provenance` job runs only after static quality succeeds and only on pushes to `main` or `master`. It creates a ZIP from the exact checked-out Git commit using `git archive`, calculates SHA-256, and records the full commit, workflow name, and CI run ID in `release-provenance.json`. Both files are uploaded as one GitHub Actions artifact for 30 days.

This manifest is provenance metadata, **not a signed staging acceptance report**. It does not prove that live staging tests ran and does not authorize production deployment. Promotion remains blocked until the separate v53-v58 acceptance process is satisfied, and manual review remains required. No deployment or live customer action is performed.

Inspect the artifact and verify its hash independently before use. The GitHub Actions artifact is the source of the CI-generated archive; do not substitute a locally rebuilt ZIP.
