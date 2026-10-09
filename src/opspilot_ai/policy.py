"""Fail-closed, deterministic policy decisions for OpsPilot runs.

This is a small in-process policy-as-code layer, not an OPA integration.
No policy can grant production execution in this MVP.
"""
from __future__ import annotations

from typing import Any

POLICY_VERSION = "2026-10-01"


def evaluate_run_policy(signals: list[Any], remediation_mode: str) -> dict[str, Any]:
    """Evaluate analysis risk and produce explicit action boundaries."""
    severities = [getattr(signal, "severity", "info") for signal in signals]
    weights = {"info": 0, "low": 5, "medium": 15, "high": 30, "critical": 50}
    raw_score = sum(weights.get(level, 10) for level in severities)
    risk_score = min(100, raw_score)
    high_impact = any(level in {"high", "critical"} for level in severities)
    critical = any(level == "critical" for level in severities)
    mode_supported = remediation_mode in {"read_only", "dry_run", "sandbox"}
    return {
        "policy_version": POLICY_VERSION,
        "decision": "allow_analysis" if mode_supported else "deny",
        "risk_score": risk_score,
        "risk_band": "critical" if critical else "high" if high_impact or risk_score >= 60 else "medium" if risk_score >= 20 else "low",
        "human_approval_required": bool(high_impact or remediation_mode == "sandbox"),
        "execution_permitted": False,
        "production_writes_permitted": False,
        "shell_execution_permitted": False,
        "credential_access_permitted": False,
        "blocked_actions": [
            "production_write",
            "shell_execution",
            "credential_access",
            "autonomous_deployment",
            "destructive_schema_change",
        ],
        "rules_evaluated": [
            {"rule_id": "POL-001", "result": "pass" if mode_supported else "deny", "detail": "Only read_only, dry_run, and sandbox analysis modes are supported."},
            {"rule_id": "POL-002", "result": "pass", "detail": "Production mutations and arbitrary command execution are always disabled."},
            {"rule_id": "POL-003", "result": "review" if high_impact else "pass", "detail": "High/critical signals require human review before any proposed recovery is considered."},
            {"rule_id": "POL-004", "result": "review" if remediation_mode == "sandbox" else "pass", "detail": "Sandbox mode is a disposable-fixture simulation only."},
        ],
        "limitations": ["In-process policy evaluator; not a substitute for identity-aware authorization or an external policy engine."],
    }
