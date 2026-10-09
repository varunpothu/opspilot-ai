from __future__ import annotations

from types import SimpleNamespace

from opspilot_ai.audit import build_audit_chain, verify_audit_chain
from opspilot_ai.policy import evaluate_run_policy
from opspilot_ai.triage import assess_incident


def signal(kind: str, severity: str = "high"):
    return SimpleNamespace(signal_type=kind, severity=severity)


def test_policy_is_fail_closed_for_every_supported_mode():
    for mode in ("read_only", "dry_run", "sandbox"):
        decision = evaluate_run_policy([signal("pipeline_failure")], mode)
        assert decision["decision"] == "allow_analysis"
        assert decision["execution_permitted"] is False
        assert decision["production_writes_permitted"] is False
        assert decision["shell_execution_permitted"] is False
        assert decision["credential_access_permitted"] is False
        assert "production_write" in decision["blocked_actions"]
        assert decision["human_approval_required"] is True


def test_policy_denies_unknown_mode():
    assert evaluate_run_policy([], "execute")["decision"] == "deny"


def test_triage_fingerprint_is_stable_and_correlates_related_signals():
    signals = [signal("pipeline_failure"), signal("stale_dashboard", "medium")]
    first = assess_incident("warehouse_a", signals)
    second = assess_incident("warehouse_a", list(reversed(signals)))
    assert first["incident_fingerprint"] == second["incident_fingerprint"]
    assert first["priority"] == "P2"
    assert first["correlated_groups"][0]["group_id"] == "pipeline_to_dashboard"
    assert first["recommended_next_steps"]


def test_triage_fingerprint_scopes_target_and_signal_types():
    one = assess_incident("warehouse_a", [signal("schema_drift")])
    two = assess_incident("warehouse_b", [signal("schema_drift")])
    assert one["incident_fingerprint"] != two["incident_fingerprint"]


def test_audit_chain_verifies_and_detects_tampering():
    records = build_audit_chain(
        "run-1",
        [{"status": "running"}, {"status": "succeeded"}],
        {"source.json": "a" * 64},
        {"decision": "allow_analysis", "execution_permitted": False},
        {"priority": "P2"},
    )
    assert verify_audit_chain(records)["valid"] is True
    records[1]["payload"]["status"] = "failed"
    report = verify_audit_chain(records)
    assert report["valid"] is False
    assert any("record_hash_mismatch" in error for error in report["errors"])


def test_empty_audit_chain_fails_closed():
    report = verify_audit_chain([])
    assert report["valid"] is False
    assert report["record_count"] == 0
    assert "empty_chain" in report["errors"]
