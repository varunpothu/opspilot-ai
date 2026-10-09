"""Deterministic incident correlation, prioritisation, and stable fingerprints."""
from __future__ import annotations

import hashlib
import json
from typing import Any

SEVERITY_POINTS = {"info": 0, "low": 5, "medium": 15, "high": 30, "critical": 50}

_CORRELATION_RULES = (
    ({"pipeline_failure", "stale_dashboard"}, "pipeline_to_dashboard", "Pipeline failure may explain dashboard staleness."),
    ({"stale_data", "stale_dashboard"}, "freshness_chain", "Stale source data may propagate into the dashboard."),
    ({"schema_drift", "dashboard_mismatch"}, "schema_to_semantics", "Schema drift may affect downstream metric interpretation."),
    ({"slow_pipeline", "stale_data"}, "latency_to_freshness", "Pipeline latency may contribute to a freshness breach."),
    ({"null_rate_spike", "dashboard_mismatch"}, "quality_to_metrics", "Source quality degradation may affect reported metrics."),
)


def assess_incident(target: str, signals: list[Any]) -> dict[str, Any]:
    types = sorted({str(getattr(signal, "signal_type", "unknown")) for signal in signals})
    canonical = json.dumps({"target": target, "signal_types": types}, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    score = min(100, sum(SEVERITY_POINTS.get(getattr(signal, "severity", "info"), 10) for signal in signals))
    if any(getattr(signal, "severity", "") == "critical" for signal in signals) or score >= 80:
        priority = "P1"
    elif score >= 45 or any(getattr(signal, "severity", "") == "high" for signal in signals):
        priority = "P2"
    elif score >= 15:
        priority = "P3"
    else:
        priority = "P4"
    groups = []
    for required, group_id, explanation in _CORRELATION_RULES:
        overlap = sorted(required.intersection(types))
        if len(overlap) >= 2:
            groups.append({"group_id": group_id, "signal_types": overlap, "explanation": explanation})
    next_steps = []
    if "pipeline_failure" in types:
        next_steps.append("Inspect the pipeline error and upstream dependency status before retrying.")
    if "schema_drift" in types:
        next_steps.append("Compare changed fields with the approved data contract; do not auto-accept schema changes.")
    if "stale_data" in types or "stale_dashboard" in types:
        next_steps.append("Trace freshness timestamps from source through pipeline to dashboard.")
    if "null_rate_spike" in types:
        next_steps.append("Check upstream quality and quarantine suspect records before downstream publication.")
    if "dashboard_mismatch" in types:
        next_steps.append("Reconcile source and dashboard metric snapshots and verify transformation lineage.")
    if "slow_pipeline" in types:
        next_steps.append("Compare recorded duration against the SLO and inspect the slowest stage.")
    if "data_contract_violation" in types:
        next_steps.append("Validate the versioned data contract and quarantine non-conforming records before publication.")
    if not next_steps:
        next_steps.append("No configured incident signal was detected; continue routine monitoring.")
    return {
        "incident_fingerprint": fingerprint,
        "priority": priority,
        "risk_score": score,
        "signal_count": len(signals),
        "signal_types": types,
        "correlated_groups": groups,
        "recommended_next_steps": next_steps,
        "fingerprint_scope": "target plus sorted unique signal types; this is a grouping key, not proof that two runs share a root cause.",
    }
