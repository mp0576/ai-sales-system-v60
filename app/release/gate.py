"""Fail-closed release gate: static repository checks plus staging config checks.

This module never makes network requests and never prints secret values. It does not
certify a live Supabase project; use the staging probes separately for that evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import re

EXPECTED_MIGRATIONS = (
    "0001_core.sql",
    "0002_rls.sql",
    "0003_outbox_claim.sql",
    "0004_worker_runtime.sql",
    "0011_dashboard.sql",
    "0012_customer_lifecycle.sql",
    "0013_dashboard_persistence.sql",
    "0014_runtime_persistence.sql",
    "0015_permanent_outbox_failures.sql",
    "0016_rls_privilege_hardening.sql",
    "0017_durable_action_idempotency.sql",
    "0018_provider_webhook_inbox.sql",
    "0019_durable_exception_center.sql",
    "0020_audited_replay_approvals.sql",
    "0021_controlled_replay_dispatch.sql",
    "0022_real_estate_lead_persistence.sql",
    "0023_operational_lead_api.sql",
    "0024_operational_lead_concurrency.sql",
)

@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    detail: str
    blocking: bool = True


def _https_project_origin(value: str) -> bool:
    parsed = urlparse((value or "").strip())
    return (parsed.scheme == "https" and bool(parsed.netloc)
            and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
            and not parsed.username and not parsed.password)


def static_checks(root: Path) -> list[GateCheck]:
    checks: list[GateCheck] = []
    # Keep Python RPC callers and the latest SQL function definitions synchronized.
    try:
        from scripts.check_rpc_contracts import check_contracts
        rpc_checks = check_contracts(root)
        rpc_failed = [name for name, passed, _ in rpc_checks if not passed]
        checks.append(GateCheck("rpc_contracts", not rpc_failed,
                                "Python RPC arguments and privileged function grants match SQL migrations"
                                if not rpc_failed else "RPC contract drift: " + ", ".join(rpc_failed)))
    except Exception:
        checks.append(GateCheck("rpc_contracts", False, "RPC contract checker failed to run"))
    migrations_dir = root / "sql" / "migrations"
    present = sorted(p.name for p in migrations_dir.glob("*.sql")) if migrations_dir.exists() else []
    missing = [name for name in EXPECTED_MIGRATIONS if name not in present]
    checks.append(GateCheck("migration_manifest", not missing,
                            "all documented migrations present" if not missing else "missing: " + ", ".join(missing)))

    guide = (root / "sql" / "MIGRATIONS.md").read_text(encoding="utf-8") if (root / "sql" / "MIGRATIONS.md").exists() else ""
    positions = [guide.find(name) for name in EXPECTED_MIGRATIONS]
    ordered = all(pos >= 0 for pos in positions) and positions == sorted(positions)
    checks.append(GateCheck("migration_order_documented", ordered,
                            "migration guide lists files in numeric application order" if ordered else "migration guide is missing or misorders required files"))

    concurrency_path = migrations_dir / "0024_operational_lead_concurrency.sql"
    concurrency_sql = concurrency_path.read_text(encoding="utf-8").lower() if concurrency_path.exists() else ""
    concurrency_tokens = (
        "pg_advisory_xact_lock",
        "':idem:'",
        "':lead:'",
        "auth.uid()",
        "set search_path = public, pg_temp",
        "grant execute on function public.save_operational_lead_snapshot",
        " to authenticated",
    )
    concurrency_missing = [token for token in concurrency_tokens if token not in concurrency_sql]
    adapter_path = root / "app" / "dashboard" / "supabase_leads.py"
    adapter_source = adapter_path.read_text(encoding="utf-8").lower() if adapter_path.exists() else ""
    if "40001" not in adapter_source or "23505" not in adapter_source:
        concurrency_missing.append("PostgREST SQLSTATE conflict normalization")
    checks.append(GateCheck("hosted_lead_concurrency_v52", not concurrency_missing,
                            "advisory locks, tenant auth, stable RPC grants and conflict normalization present"
                            if not concurrency_missing else "missing v52 guardrails: " + ", ".join(concurrency_missing)))

    hardening_path = migrations_dir / "0016_rls_privilege_hardening.sql"
    sql = hardening_path.read_text(encoding="utf-8").lower() if hardening_path.exists() else ""
    required_sql = (
        "grant execute on function public.claim_outbox(integer, text, integer) to service_role",
        "revoke all on function public.claim_outbox(integer, text, integer) from public, anon, authenticated",
        "grant execute on function public.resolve_dashboard_approval(uuid, uuid, boolean, text) to authenticated",
        "auth.uid()",
        "organization_members",
    )
    absent = [token for token in required_sql if token not in sql]
    checks.append(GateCheck("sql_privilege_guardrails", not absent,
                            "required privilege/auth checks present" if not absent else "missing SQL guardrails: " + ", ".join(absent)))

    idempotency_path = migrations_dir / "0017_durable_action_idempotency.sql"
    idempotency_sql = idempotency_path.read_text(encoding="utf-8").lower() if idempotency_path.exists() else ""
    durable_tokens = (
        "unique (organization_id, action_type, idempotency_key)",
        "for update",
        "grant execute on function public.claim_action_idempotency(uuid,text,text,text,integer) to service_role",
        "grant execute on function public.finish_action_idempotency(uuid,text,text,text,jsonb,boolean) to service_role",
        "revoke all on function public.claim_action_idempotency(uuid,text,text,text,integer) from public, anon, authenticated",
    )
    durable_absent = [token for token in durable_tokens if token not in idempotency_sql]
    checks.append(GateCheck("durable_idempotency_guardrails", not durable_absent,
                            "durable idempotency uniqueness, locking and service-role grants present" if not durable_absent else "missing durable idempotency guardrails: " + ", ".join(durable_absent)))


    webhook_path = migrations_dir / "0018_provider_webhook_inbox.sql"
    webhook_sql = webhook_path.read_text(encoding="utf-8").lower() if webhook_path.exists() else ""
    webhook_tokens = (
        "unique (organization_id, provider, event_id)",
        "for update",
        "grant execute on function public.claim_provider_webhook(uuid,text,text,text,integer,timestamptz,text) to service_role",
        "grant execute on function public.finish_provider_webhook(uuid,text,text,text,boolean,text) to service_role",
        "revoke all on function public.claim_provider_webhook(uuid,text,text,text,integer,timestamptz,text) from public, anon, authenticated",
    )
    webhook_absent = [token for token in webhook_tokens if token not in webhook_sql]
    checks.append(GateCheck("durable_webhook_inbox_guardrails", not webhook_absent,
                            "webhook inbox uniqueness, row locking and service-role grants present" if not webhook_absent else "missing webhook inbox guardrails: " + ", ".join(webhook_absent)))

    security_matrix = root / "sql" / "staging_security_matrix.sql"
    matrix_sql = security_matrix.read_text(encoding="utf-8").lower() if security_matrix.exists() else ""
    matrix_tokens = ("has_table_privilege", "relrowsecurity", "aclexplode", "claim_provider_webhook", "resolve_dashboard_approval")
    matrix_absent = [token for token in matrix_tokens if token not in matrix_sql]
    matrix_mutations = any(token in matrix_sql for token in ("insert into ", "update public.", "delete from ", "alter table ", "grant ", "revoke "))
    checks.append(GateCheck("staging_security_matrix", bool(matrix_sql) and not matrix_absent and not matrix_mutations,
                            "read-only staging security matrix covers RLS, table privileges and sensitive RPC grants" if matrix_sql and not matrix_absent and not matrix_mutations else "missing/incomplete or potentially mutating staging security matrix"))

    try:
        from scripts.check_pilot_readiness import check_report
        readiness_ok, readiness_missing = check_report(root)
        checks.append(GateCheck("pilot_readiness_report", readiness_ok,
                                "pilot blockers, safe defaults and NO-GO decision documented" if readiness_ok else "incomplete pilot readiness report: " + ", ".join(readiness_missing)))
    except Exception:
        checks.append(GateCheck("pilot_readiness_report", False, "pilot readiness report checker failed to run"))

    pilot_ops_path = root / "PILOT_OPERATIONS_V30.md"
    pilot_ops = pilot_ops_path.read_text(encoding="utf-8").lower() if pilot_ops_path.exists() else ""
    pilot_ops_tokens = ("does not write to a database", "never infer consent", "opt-out", "payments disabled", "live launch remains blocked")
    pilot_ops_missing = [token for token in pilot_ops_tokens if token not in pilot_ops]
    lead_validator = root / "scripts" / "validate_pilot_leads.py"
    lead_module = root / "app" / "pilot" / "lead_import.py"
    ops_ok = bool(pilot_ops) and not pilot_ops_missing and lead_validator.exists() and lead_module.exists()
    checks.append(GateCheck("pilot_operations_pack", ops_ok,
                            "lead intake validator and safe pilot operating guidance present" if ops_ok else "missing pilot operations guidance, consent safeguards, or lead validator"))

    monitoring_doc = root / "PILOT_MONITORING_V31.md"
    monitoring_text = monitoring_doc.read_text(encoding="utf-8").lower() if monitoring_doc.exists() else ""
    monitoring_tokens = ("read-only", "provider_outcome_unknown", "other organizations", "drops names", "live outbound and payments disabled")
    monitoring_missing = [token for token in monitoring_tokens if token not in monitoring_text]
    monitoring_ok = (not monitoring_missing and (root / "scripts" / "daily_pilot_report.py").exists()
                     and (root / "app" / "pilot" / "monitoring.py").exists())
    checks.append(GateCheck("pilot_monitoring_pack", monitoring_ok,
                            "tenant-scoped daily report, privacy safeguards and alert runbook present" if monitoring_ok else "missing monitoring files or safeguards: " + ", ".join(monitoring_missing)))

    exception_doc = root / "EXCEPTION_CENTER_V32.md"
    exception_text = exception_doc.read_text(encoding="utf-8").lower() if exception_doc.exists() else ""
    exception_tokens = ("tenant-scoped", "idempotent", "raw provider errors", "manager-level role", "live persistence is not implemented")
    exception_missing = [token for token in exception_tokens if token not in exception_text]
    exception_ok = (not exception_missing and (root / "scripts" / "exception_queue.py").exists()
                    and (root / "app" / "pilot" / "exceptions.py").exists())
    checks.append(GateCheck("exception_center_pack", exception_ok,
                            "tenant-scoped exception queue, role checks and limitations documented" if exception_ok else "missing exception center files or safeguards: " + ", ".join(exception_missing)))

    durable_exception_path = migrations_dir / "0019_durable_exception_center.sql"
    durable_exception_sql = durable_exception_path.read_text(encoding="utf-8").lower() if durable_exception_path.exists() else ""
    durable_exception_tokens = (
        "unique (organization_id, source_type, source_id)", "for update",
        "operational_exception_audit", "organization_members",
        "grant select, insert on public.operational_exception_audit to service_role",
        "grant execute on function public.create_operational_exception(uuid,text,text,text,text,text) to service_role",
        "grant execute on function public.transition_operational_exception(uuid,uuid,uuid,text,uuid,text) to service_role",
        "revoke all on function public.transition_operational_exception(uuid,uuid,uuid,text,uuid,text) from public, anon, authenticated",
    )
    durable_exception_missing = [token for token in durable_exception_tokens if token not in durable_exception_sql]
    checks.append(GateCheck("durable_exception_center_guardrails", not durable_exception_missing,
                            "tenant uniqueness, row locking, atomic audit and service-role-only RPCs present" if not durable_exception_missing else "missing durable exception safeguards: " + ", ".join(durable_exception_missing)))

    worker_path = root / "app" / "workers" / "durable_service.py"
    worker_source = worker_path.read_text(encoding="utf-8").lower() if worker_path.exists() else ""
    worker_doc = root / "WORKER_EXCEPTION_INTEGRATION_V34.md"
    worker_doc_text = worker_doc.read_text(encoding="utf-8").lower() if worker_doc.exists() else ""
    worker_tokens = ("exception_store", "_record_dead_letter", "max_attempts", "source_type=\"outbox\"", "exceptions_persisted", "exception_errors")
    worker_missing = [token for token in worker_tokens if token not in worker_source]
    worker_doc_tokens = ("dead_letter", "max_attempts", "payloads", "staging", "outbound_enabled=false", "enable_live_payments=false")
    worker_doc_missing = [token for token in worker_doc_tokens if token not in worker_doc_text]
    worker_ok = not worker_missing and not worker_doc_missing
    checks.append(GateCheck("worker_exception_integration", worker_ok,
                            "dead-letter exception wiring, retry budget and staging limits documented" if worker_ok else "missing worker exception safeguards: " + ", ".join(worker_missing + worker_doc_missing)))

    replay_policy_path = root / "app" / "pilot" / "replay_policy.py"
    replay_cli_path = root / "scripts" / "exception_replay_plan.py"
    replay_doc_path = root / "EXCEPTION_REPLAY_POLICY_V35.md"
    replay_policy = replay_policy_path.read_text(encoding="utf-8").lower() if replay_policy_path.exists() else ""
    replay_doc = replay_doc_path.read_text(encoding="utf-8").lower() if replay_doc_path.exists() else ""
    replay_tokens = ("external_outcome", "idempotency_key", "max_replays", "execute")
    replay_missing = [token for token in replay_tokens if token not in replay_policy]
    replay_doc_tokens = ("read-only", "not applied", "idempotency key", "no live", "supabase")
    replay_doc_missing = [token for token in replay_doc_tokens if token not in replay_doc]
    replay_ok = not replay_missing and not replay_doc_missing and replay_cli_path.exists()
    checks.append(GateCheck("controlled_exception_replay_policy", replay_ok,
                            "bounded fail-closed replay planner and read-only CLI documented" if replay_ok else "missing replay safety controls: " + ", ".join(replay_missing + replay_doc_missing)))

    replay_migration_path = migrations_dir / "0020_audited_replay_approvals.sql"
    replay_sql = replay_migration_path.read_text(encoding="utf-8").lower() if replay_migration_path.exists() else ""
    replay_sql_tokens = ("exception_replay_requests", "exception_replay_audit", "for update",
                         "requester cannot approve own replay", "not_applied",
                         "unique (organization_id, exception_id, replay_number)",
                         "grant execute on function public.request_exception_replay",
                         "grant execute on function public.decide_exception_replay")
    replay_sql_missing = [token for token in replay_sql_tokens if token not in replay_sql]
    replay_doc_path = root / "AUDITED_REPLAY_APPROVALS_V36.md"
    replay_doc = replay_doc_path.read_text(encoding="utf-8").lower() if replay_doc_path.exists() else ""
    replay_doc_tokens = ("no provider dispatch", "requester cannot approve", "idempotency key", "tenant", "staging")
    replay_doc_missing = [token for token in replay_doc_tokens if token not in replay_doc]
    replay_ok = not replay_sql_missing and not replay_doc_missing and (root / "tests" / "test_v36_replay_approvals.py").exists()
    checks.append(GateCheck("audited_replay_approvals", replay_ok,
                            "tenant-scoped replay requests, atomic audit and separate-actor approval documented" if replay_ok else "missing replay approval safeguards: " + ", ".join(replay_sql_missing + replay_doc_missing)))

    dispatch_sql_path = migrations_dir / "0021_controlled_replay_dispatch.sql"
    dispatch_sql = dispatch_sql_path.read_text(encoding="utf-8").lower() if dispatch_sql_path.exists() else ""
    dispatch_source_path = root / "app" / "workers" / "replay_dispatcher.py"
    dispatch_source = dispatch_source_path.read_text(encoding="utf-8").lower() if dispatch_source_path.exists() else ""
    dispatch_doc_path = root / "CONTROLLED_REPLAY_DISPATCH_V37.md"
    dispatch_doc = dispatch_doc_path.read_text(encoding="utf-8").lower() if dispatch_doc_path.exists() else ""
    dispatch_tokens = ("for update skip locked", "status='approved'", "reconciliation_required", "dispatch_lease_until < now()", "claim_exception_replay", "finish_exception_replay")
    dispatch_missing = [token for token in dispatch_tokens if token not in dispatch_sql]
    source_tokens = ("idempotency_key", "outcome_unknown", "finish_persistence_failed", "not_dispatched")
    source_missing = [token for token in source_tokens if token not in dispatch_source]
    doc_tokens = ("at-least-once", "provider idempotency", "expired", "staging", "no automatic redispatch")
    doc_missing = [token for token in doc_tokens if token not in dispatch_doc]
    dispatch_ok = not dispatch_missing and not source_missing and not doc_missing and (root / "tests" / "test_v37_replay_dispatcher.py").exists()
    checks.append(GateCheck("controlled_replay_dispatch", dispatch_ok,
                            "atomic claim, bounded lease, preserved idempotency and ambiguous-outcome reconciliation documented" if dispatch_ok else "missing dispatch safeguards: " + ", ".join(dispatch_missing + source_missing + doc_missing)))

    staging_acceptance_sql = root / "sql" / "staging_replay_dispatch_acceptance.sql"
    staging_acceptance_source = staging_acceptance_sql.read_text(encoding="utf-8").lower() if staging_acceptance_sql.exists() else ""
    staging_acceptance_cli = root / "scripts" / "verify_staging_acceptance.py"
    staging_acceptance_tokens = ("has_function_privilege", "relrowsecurity", "for update skip locked", "select")
    staging_acceptance_missing = [token for token in staging_acceptance_tokens if token not in staging_acceptance_source]
    staging_acceptance_mutating = any(token in staging_acceptance_source for token in ("insert into ", "update public.", "delete from ", "alter table ", "grant ", "revoke "))
    staging_acceptance_ok = bool(staging_acceptance_source) and not staging_acceptance_missing and not staging_acceptance_mutating and staging_acceptance_cli.exists() and (root / "tests" / "test_v38_staging_acceptance.py").exists()
    checks.append(GateCheck("staging_replay_acceptance_pack", staging_acceptance_ok,
                            "read-only replay dispatch catalog probe and fail-closed CSV evaluator present" if staging_acceptance_ok else "missing or unsafe staging acceptance components: " + ", ".join(staging_acceptance_missing)))

    rehearsal_cli = root / "scripts" / "verify_staging_rehearsal.py"
    rehearsal_source = rehearsal_cli.read_text(encoding="utf-8").lower() if rehearsal_cli.exists() else ""
    rehearsal_tests = root / "tests" / "test_v39_staging_rehearsal.py"
    rehearsal_tokens = ("required_checks", "evidence_sha256", "go_for_manual_review", "no-go", "cannot independently prove")
    rehearsal_missing = [token for token in rehearsal_tokens if token not in rehearsal_source]
    rehearsal_doc = root / "STAGING_REHEARSAL_EVIDENCE_V39.md"
    rehearsal_doc_text = rehearsal_doc.read_text(encoding="utf-8").lower() if rehearsal_doc.exists() else ""
    rehearsal_doc_tokens = ("manual review", "sha-256 digest", "no-go", "not launch authorization", "live outbound and payments")
    rehearsal_doc_missing = [token for token in rehearsal_doc_tokens if token not in rehearsal_doc_text]
    rehearsal_ok = bool(rehearsal_source) and not rehearsal_missing and not rehearsal_doc_missing and rehearsal_tests.exists()
    checks.append(GateCheck("staging_rehearsal_evidence_pack", rehearsal_ok,
                            "fail-closed operational evidence manifest verifier and limitations documented" if rehearsal_ok else "missing rehearsal evidence safeguards: " + ", ".join(rehearsal_missing + rehearsal_doc_missing)))

    rehearsal_runner = root / "scripts" / "run_staging_rehearsal.py"
    rehearsal_runner_tests = root / "tests" / "test_v40_staging_runner.py"
    rehearsal_runner_source = rehearsal_runner.read_text(encoding="utf-8").lower() if rehearsal_runner.exists() else ""
    runner_tokens = ("--execute", "app_env", "production", "evidence_sha256", "concurrent_claim_single_winner", "provider_idempotency_duplicate_suppressed")
    runner_missing = [token for token in runner_tokens if token not in rehearsal_runner_source]
    runner_doc = root / "STAGING_REHEARSAL_RUNNER_V40.md"
    runner_doc_source = runner_doc.read_text(encoding="utf-8").lower() if runner_doc.exists() else ""
    runner_doc_tokens = ("read-only", "refuses production", "marks these checks as fail", "never launch authorization")
    runner_doc_missing = [token for token in runner_doc_tokens if token not in runner_doc_source]
    runner_ok = bool(rehearsal_runner_source) and not runner_missing and not runner_doc_missing and rehearsal_runner_tests.exists()
    checks.append(GateCheck("staging_rehearsal_runner", runner_ok,
                            "opt-in read-only staging evidence runner fails closed on unimplemented checks" if runner_ok else "missing runner safeguards: " + ", ".join(runner_missing + runner_doc_missing)))

    replay_concurrency_tests = root / "tests" / "test_v41_replay_concurrency.py"
    replay_dispatcher = root / "app" / "workers" / "replay_dispatcher.py"
    replay_concurrency_doc = root / "V41_REPLAY_CONCURRENCY_AND_CRASH_TESTS.md"
    concurrency_source = replay_concurrency_tests.read_text(encoding="utf-8").lower() if replay_concurrency_tests.exists() else ""
    concurrency_doc_source = replay_concurrency_doc.read_text(encoding="utf-8").lower() if replay_concurrency_doc.exists() else ""
    concurrency_tokens = ("threadpoolexecutor", "idempotency_key", "outcome_unknown", "finish_persistence_failed")
    concurrency_missing = [token for token in concurrency_tokens if token not in concurrency_source]
    concurrency_doc_tokens = ("in-memory store", "live staging", "provider sandbox")
    concurrency_doc_missing = [token for token in concurrency_doc_tokens if token not in concurrency_doc_source]
    concurrency_ok = replay_concurrency_tests.exists() and replay_dispatcher.exists() and not concurrency_missing and not concurrency_doc_missing
    checks.append(GateCheck("replay_concurrency_crash_tests", concurrency_ok,
                            "concurrency race and ambiguous provider crash-window tests documented with staging limitations" if concurrency_ok else "missing replay concurrency safeguards: " + ", ".join(concurrency_missing + concurrency_doc_missing)))

    recovery_script = root / "scripts" / "reconcile_expired_replays.py"
    recovery_tests = root / "tests" / "test_v42_expired_replay_recovery.py"
    recovery_doc = root / "EXPIRED_REPLAY_RECOVERY_V42.md"
    recovery_source = recovery_script.read_text(encoding="utf-8").lower() if recovery_script.exists() else ""
    recovery_doc_source = recovery_doc.read_text(encoding="utf-8").lower() if recovery_doc.exists() else ""
    recovery_sql = dispatch_sql
    recovery_tokens = ("--execute", 'env != "staging"', "reconcile_expired_replays", "none were re-dispatched")
    recovery_missing = [token for token in recovery_tokens if token not in recovery_source]
    recovery_sql_tokens = ("reconcile_expired_exception_replays", "status='reconciliation_required'", "from public, anon, authenticated", "to service_role")
    recovery_sql_missing = [token for token in recovery_sql_tokens if token not in recovery_sql]
    recovery_doc_tokens = ("no `--execute`", "app_env=staging", "never automatically dispatched", "provider sandbox")
    recovery_doc_missing = [token for token in recovery_doc_tokens if token not in recovery_doc_source]
    recovery_ok = recovery_script.exists() and recovery_tests.exists() and recovery_doc.exists() and not recovery_missing and not recovery_sql_missing and not recovery_doc_missing
    checks.append(GateCheck("expired_replay_recovery", recovery_ok,
                            "staging-only explicit lease reconciliation, SQL audit path and fail-closed tests present" if recovery_ok else "missing expired replay recovery safeguards: " + ", ".join(recovery_missing + recovery_sql_missing + recovery_doc_missing)))

    evidence_verifier = root / "scripts" / "verify_staging_rehearsal.py"
    evidence_tests = root / "tests" / "test_v43_evidence_integrity.py"
    evidence_doc = root / "STAGING_EVIDENCE_INTEGRITY_V43.md"
    evidence_source = evidence_verifier.read_text(encoding="utf-8").lower() if evidence_verifier.exists() else ""
    evidence_doc_source = evidence_doc.read_text(encoding="utf-8").lower() if evidence_doc.exists() else ""
    evidence_tokens = ("--evidence-root", "sha-256 does not match", "contains a symlink", "safe relative path", "is empty")
    evidence_missing = [token for token in evidence_tokens if token not in evidence_source]
    evidence_doc_tokens = ("traversal", "sha-256", "nunca autorização de lançamento")
    evidence_doc_missing = [token for token in evidence_doc_tokens if token not in evidence_doc_source]
    evidence_ok = evidence_verifier.exists() and evidence_tests.exists() and evidence_doc.exists() and not evidence_missing and not evidence_doc_missing
    checks.append(GateCheck("staging_evidence_integrity_v43", evidence_ok,
                            "manifest artifacts are checked against on-disk SHA-256 and unsafe paths are rejected" if evidence_ok else "missing evidence-integrity safeguards: " + ", ".join(evidence_missing + evidence_doc_missing)))

    concurrency_probe = root / "scripts" / "staging_concurrent_replay_claim.py"
    concurrency_tests = root / "tests" / "test_v44_staging_concurrency_probe.py"
    concurrency_doc = root / "STAGING_CONCURRENCY_PROBE_V44.md"
    concurrency_source = concurrency_probe.read_text(encoding="utf-8").lower() if concurrency_probe.exists() else ""
    concurrency_doc_source = concurrency_doc.read_text(encoding="utf-8").lower() if concurrency_doc.exists() else ""
    concurrency_tokens = ("--confirm-disposable-fixture", 'env.get("app_env", "").strip().lower() != "staging"',
                          "threadpoolexecutor", '"outcome_unknown"', "external_provider_called")
    concurrency_missing = [token for token in concurrency_tokens if token not in concurrency_source]
    concurrency_doc_tokens = ("disposable", "outcome_unknown", "never invokes a provider", "service-role")
    concurrency_doc_missing = [token for token in concurrency_doc_tokens if token not in concurrency_doc_source]
    concurrency_ok = concurrency_probe.exists() and concurrency_tests.exists() and concurrency_doc.exists() and not concurrency_missing and not concurrency_doc_missing
    checks.append(GateCheck("staging_concurrent_replay_claim_v44", concurrency_ok,
                            "opt-in two-worker staging claim probe and safe reconciliation cleanup documented" if concurrency_ok else "missing staging concurrency probe safeguards: " + ", ".join(concurrency_missing + concurrency_doc_missing)))

    security_acceptance = root / "scripts" / "staging_security_acceptance.py"
    security_tests = root / "tests" / "test_v45_staging_security_acceptance.py"
    freshness_doc = root / "STAGING_EVIDENCE_FRESHNESS_V46.md"
    security_doc = root / "STAGING_SECURITY_ACCEPTANCE_V45.md"
    security_source = security_acceptance.read_text(encoding="utf-8").lower() if security_acceptance.exists() else ""
    security_doc_source = security_doc.read_text(encoding="utf-8").lower() if security_doc.exists() else ""
    security_tokens = ("app_env", "tenant_isolation", "external_provider_called", "evidence_sha256", "no_go", "evidence_timestamp_out_of_window", "fixture_identity_invalid")
    security_missing = [token for token in security_tokens if token not in security_source]
    security_doc_tokens = ("read-only", "no_go", "not a security certification", "sha-256")
    security_doc_missing = [token for token in security_doc_tokens if token not in security_doc_source]
    security_ok = security_acceptance.exists() and security_tests.exists() and security_doc.exists() and freshness_doc.exists() and not security_missing and not security_doc_missing
    checks.append(GateCheck("staging_security_acceptance_v46", security_ok,
                            "tenant-isolation and concurrency evidence require fresh timestamps, valid fixture IDs and complete cleanup" if security_ok else "missing staging security acceptance safeguards: " + ", ".join(security_missing + security_doc_missing)))

    signing_script = root / "scripts" / "sign_staging_evidence.py"
    signing_tests = root / "tests" / "test_v47_signed_staging_evidence.py"
    signing_doc = root / "STAGING_EVIDENCE_SIGNING_V47.md"
    signing_source = signing_script.read_text(encoding="utf-8").lower() if signing_script.exists() else ""
    signing_doc_source = signing_doc.read_text(encoding="utf-8").lower() if signing_doc.exists() else ""
    signing_tokens = ("hmac-sha256", "compare_digest", "staging_evidence_hmac_key", "signature_mismatch")
    signing_missing = [token for token in signing_tokens if token not in signing_source]
    signing_doc_tokens = ("at least 32", "does not execute tests", "not a launch authorization")
    signing_doc_missing = [token for token in signing_doc_tokens if token not in signing_doc_source]
    signing_ok = signing_script.exists() and signing_tests.exists() and signing_doc.exists() and not signing_missing and not signing_doc_missing
    checks.append(GateCheck("signed_staging_evidence_v47", signing_ok,
                            "staging JSON reports can be HMAC-signed and verified; limits documented" if signing_ok else "missing signed-evidence safeguards: " + ", ".join(signing_missing + signing_doc_missing)))

    real_estate_module = root / "app" / "simulation" / "real_estate.py"
    real_estate_cli = root / "scripts" / "simulate_real_estate_golden_path.py"
    real_estate_tests = root / "tests" / "test_v48_real_estate_journey.py"
    real_estate_doc = root / "REAL_ESTATE_GOLDEN_PATH_V48.md"
    real_estate_source = real_estate_module.read_text(encoding="utf-8").lower() if real_estate_module.exists() else ""
    real_estate_tokens = ("tenant mismatch", "consent_missing", "human_approval_required", "external_side_effect", "do_not_contact")
    real_estate_missing = [token for token in real_estate_tokens if token not in real_estate_source]
    real_estate_ok = all(p.exists() for p in (real_estate_module, real_estate_cli, real_estate_tests, real_estate_doc)) and not real_estate_missing
    checks.append(GateCheck("real_estate_golden_path_v48", real_estate_ok,
                            "offline real-estate lead simulation, consent/tenant guards, human review and tests present" if real_estate_ok else "missing real-estate simulation safeguards or artifacts: " + ", ".join(real_estate_missing)))

    env_example = (root / ".env.example").read_text(encoding="utf-8") if (root / ".env.example").exists() else ""
    obvious_live_defaults = bool(re.search(r"(?im)^\s*(?:OUTBOUND_ENABLED|ENABLE_LIVE_PAYMENTS)\s*=\s*true\s*$", env_example))
    checks.append(GateCheck("safe_example_defaults", not obvious_live_defaults,
                            "example config does not enable live outbound/payments by default" if not obvious_live_defaults else "example config enables live outbound or payments"))

    secrets = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        if path.name in {".env", ".env.production", ".env.staging"}:
            secrets.append(path.name)
    checks.append(GateCheck("no_local_env_files_in_release", not secrets,
                            "no local environment files found" if not secrets else "local environment file(s) must be removed: " + ", ".join(sorted(set(secrets)))))
    lead_migration = migrations_dir / "0022_real_estate_lead_persistence.sql"
    lead_sql = lead_migration.read_text(encoding="utf-8").lower() if lead_migration.exists() else ""
    lead_tokens = ("primary key (organization_id, lead_id)", "real_estate_lead_idempotency", "real_estate_lead_events", "enable row level security", "from public, anon, authenticated", "to service_role")
    lead_missing = [token for token in lead_tokens if token not in lead_sql]
    lead_pack_ok = (not lead_missing and (root / "app" / "repositories" / "real_estate_leads.py").exists()
                    and (root / "tests" / "test_v49_lead_persistence.py").exists()
                    and (root / "REAL_ESTATE_LEAD_PERSISTENCE_V49.md").exists())
    checks.append(GateCheck("real_estate_lead_persistence_v49", lead_pack_ok,
                            "tenant-scoped persistence, idempotency, audit, tests and limitations documented" if lead_pack_ok else "missing lead persistence guardrails or pack files: " + ", ".join(lead_missing)))

    api_path = root / "app" / "dashboard" / "api.py"
    api_source = api_path.read_text(encoding="utf-8") if api_path.exists() else ""
    v50_tests = root / "tests" / "test_v50_operational_lead_api.py"
    v50_docs = root / "V50_OPERATIONAL_LEAD_API.md"
    v50_ok = all(route in api_source for route in (
        '"/api/v1/organizations/{organization_id}/leads"',
        '"/api/v1/organizations/{organization_id}/leads/{lead_id}"',
        '"/api/v1/organizations/{organization_id}/leads/{lead_id}/events"',
        '"Idempotency-Key"',
    )) and v50_tests.exists() and v50_docs.exists()
    checks.append(GateCheck("operational_lead_api_v50", v50_ok,
                            "authenticated lead API, idempotency contract, tests and deployment limits documented"
                            if v50_ok else "missing v50 lead API routes, tests, or documentation"))

    v53_script = root / "scripts" / "verify_staging_acceptance_v53.py"
    v53_tests = root / "tests" / "test_v53_staging_acceptance_verifier.py"
    v53_docs = root / "STAGING_ACCEPTANCE_V53.md"
    v53_source = v53_script.read_text(encoding="utf-8") if v53_script.exists() else ""
    v53_ok = (v53_tests.exists() and v53_docs.exists()
              and "concurrent_first_write" in v53_source
              and "MAX_AGE_HOURS = 24" in v53_source
              and "live_outbound_enabled" in v53_source
              and "forbidden credential field" in v53_source)
    checks.append(GateCheck("staging_acceptance_evidence_v53", v53_ok,
                            "freshness, cross-tenant, concurrency, disabled-live-action and secret-leak checks present"
                            if v53_ok else "missing v53 staging evidence verifier, tests, or documentation"))

    v54_script = root / "scripts" / "verify_staging_release_v54.py"
    v54_tests = root / "tests" / "test_v54_signed_staging_release.py"
    v54_docs = root / "STAGING_RELEASE_DECISION_V54.md"
    v54_source = v54_script.read_text(encoding="utf-8") if v54_script.exists() else ""
    v54_ok = (v54_tests.exists() and v54_docs.exists()
              and "verify_envelope" in v54_source
              and "validate_evidence" in v54_source
              and "return 0 if accepted else 1" in v54_source)
    checks.append(GateCheck("signed_staging_release_decision_v54", v54_ok,
                            "HMAC integrity and v53 semantic acceptance are both required"
                            if v54_ok else "missing v54 signed staging release verifier, tests, or documentation"))

    v57_script = root / "scripts" / "verify_production_promotion_v57.py"
    v57_tests = root / "tests" / "test_v57_production_promotion_gate.py"
    v57_docs = root / "PRODUCTION_PROMOTION_GATE_V57.md"
    v57_ok = (v57_script.exists() and v57_tests.exists() and v57_docs.exists()
              and "ELIGIBLE_FOR_MANUAL_REVIEW" in v57_script.read_text(encoding="utf-8")
              and "LIVE_PAYMENTS_ENABLED" in v57_script.read_text(encoding="utf-8"))
    checks.append(GateCheck("production_promotion_gate_v57", v57_ok,
                            "fail-closed promotion gate, tests, and docs present"
                            if v57_ok else "missing or incomplete v57 production promotion gate"))

    v58_script = root / "scripts" / "verify_production_promotion_v58.py"
    v58_tests = root / "tests" / "test_v58_release_artifact_binding.py"
    v58_docs = root / "RELEASE_ARTIFACT_BINDING_V58.md"
    v58_source = v58_script.read_text(encoding="utf-8") if v58_script.exists() else ""
    v58_ok = (v58_tests.exists() and v58_docs.exists()
              and "source_commit" in v58_source
              and "artifact_sha256" in v58_source
              and "automatic_deployment" in v58_source)
    checks.append(GateCheck("release_artifact_binding_v58", v58_ok,
                            "signed staging evidence bound to commit and exact artifact; manual review only"
                            if v58_ok else "missing or incomplete v58 release artifact binding"))

    v59_script = root / "scripts" / "create_release_provenance_v59.py"
    v59_docs = root / "RELEASE_PROVENANCE_V59.md"
    v59_workflow = root / ".github" / "workflows" / "staging-acceptance-v56.yml"
    v59_ok = (v59_script.is_file() and v59_docs.is_file() and v59_workflow.is_file()
              and "release-provenance" in v59_workflow.read_text(encoding="utf-8")
              and "automatic_deployment" in v59_script.read_text(encoding="utf-8"))
    checks.append(GateCheck("ci_release_provenance_v59", v59_ok,
                            "CI-generated artifact provenance and no-auto-deploy policy present"
                            if v59_ok else "missing or incomplete v59 release provenance pack"))

    v60_intake = root / "app" / "services" / "public_demo_requests.py"
    v60_tests = root / "tests" / "test_v60_commercial_intake.py"
    v60_offer = root / "dashboard" / "offer.html"
    v60_docs = root / "COMMERCIAL_REVENUE_CYCLE_V60.md"
    v60_source = v60_intake.read_text(encoding="utf-8") if v60_intake.exists() else ""
    v60_api = (root / "app" / "dashboard" / "api.py").read_text(encoding="utf-8")
    v60_ok = (v60_tests.exists() and v60_offer.exists() and v60_docs.exists()
              and "idempotency_key" in v60_source
              and "PUBLIC_INTAKE_ADMIN_TOKEN" in v60_api
              and "/api/v1/public/demo-requests" in v60_api)
    checks.append(GateCheck("commercial_intake_v60", v60_ok,
                            "public offer, durable idempotent intake, protected admin queue and tests present"
                            if v60_ok else "missing or incomplete v60 commercial intake"))

    return checks


def staging_config_checks(env: dict[str, str]) -> list[GateCheck]:
    checks: list[GateCheck] = []
    app_env = env.get("APP_ENV", "").strip().lower()
    checks.append(GateCheck("staging_environment", app_env == "staging",
                            "APP_ENV is staging" if app_env == "staging" else "set APP_ENV=staging; live production is not accepted by this gate"))
    url = env.get("SUPABASE_URL", "").strip()
    checks.append(GateCheck("supabase_https_origin", _https_project_origin(url),
                            "Supabase URL is a valid HTTPS project origin" if _https_project_origin(url) else "SUPABASE_URL must be an HTTPS project origin without path/query"))
    anon = env.get("SUPABASE_ANON_KEY", "").strip()
    service = env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    keys_ok = bool(anon and service and anon != service and not service.startswith("sb_publishable_"))
    checks.append(GateCheck("supabase_keys_distinct", keys_ok,
                            "public and server keys are present and distinct" if keys_ok else "configure distinct SUPABASE_ANON_KEY and server-only SUPABASE_SERVICE_ROLE_KEY"))
    dashboard_token = env.get("DASHBOARD_API_TOKEN", "")
    token_ok = len(dashboard_token) >= 32 and dashboard_token not in {"replace-with-a-long-random-secret", "changeme", "secret"}
    checks.append(GateCheck("dashboard_token_strength", token_ok,
                            "dashboard token meets minimum length and is not a placeholder" if token_ok else "set a unique DASHBOARD_API_TOKEN of at least 32 characters"))
    outbound = env.get("OUTBOUND_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    payments = env.get("ENABLE_LIVE_PAYMENTS", "false").strip().lower() in {"1", "true", "yes", "on"}
    checks.append(GateCheck("live_actions_disabled", not outbound and not payments,
                            "live outbound and payments remain disabled" if not outbound and not payments else "disable OUTBOUND_ENABLED and ENABLE_LIVE_PAYMENTS during staging validation"))
    return checks


def run_gate(root: Path, env: dict[str, str], *, include_staging: bool = True) -> list[GateCheck]:
    checks = static_checks(root)
    if include_staging:
        checks.extend(staging_config_checks(env))
    return checks
