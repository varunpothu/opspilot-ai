"""Bounded-cardinality operational summary for recent persisted runs."""
from __future__ import annotations

from math import ceil
from typing import Any


def summarize_runs(runs: list[Any]) -> dict[str, Any]:
    """Summarise a bounded recent-run sample without exposing run IDs as metric labels."""
    status_counts: dict[str, int] = {}
    signal_type_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    durations: list[int] = []
    review_required = 0
    sandbox_runs = 0
    sandbox_failures = 0
    for run in runs:
        status = str(getattr(run, "status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        durations.append(max(0, int(getattr(run, "duration_ms", 0))))
        if getattr(run, "policy_decision", {}).get("human_approval_required", False):
            review_required += 1
        sandbox = getattr(run, "sandbox_result", None)
        if sandbox is not None:
            sandbox_runs += 1
            if sandbox.get("status") != "passed":
                sandbox_failures += 1
        for signal in getattr(run, "signals", []):
            signal_type = str(getattr(signal, "signal_type", "unknown"))
            severity = str(getattr(signal, "severity", "unknown"))
            signal_type_counts[signal_type] = signal_type_counts.get(signal_type, 0) + 1
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
    ordered = sorted(durations)
    p95 = ordered[max(0, ceil(0.95 * len(ordered)) - 1)] if ordered else 0
    count = len(runs)
    return {
        "scope": "most recent bounded sample; not a rolling time-window SLO",
        "sample_size": count,
        "run_status_counts": status_counts,
        "signal_counts_by_type": signal_type_counts,
        "signal_counts_by_severity": severity_counts,
        "duration_ms": {
            "mean": round(sum(ordered) / count, 2) if count else 0,
            "p95": p95,
            "max": max(ordered, default=0),
        },
        "human_review_required_runs": review_required,
        "human_review_rate": round(review_required / count, 4) if count else 0,
        "sandbox_runs": sandbox_runs,
        "sandbox_failures": sandbox_failures,
        "sandbox_failure_rate": round(sandbox_failures / sandbox_runs, 4) if sandbox_runs else 0,
        "limitations": [
            "Metrics describe only the most recent bounded sample returned by the API.",
            "This is a JSON summary, not an OpenTelemetry exporter or Prometheus endpoint.",
            "No time-window SLO or error-budget burn rate is inferred from this sample.",
        ],
    }
