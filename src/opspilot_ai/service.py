"""Local-first incident analysis. This MVP reads fixture JSON and never mutates sources."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .connectors import ConnectorError, FixtureConnector
from .models import Evidence, Hypothesis, IncidentResult, RemediationPlan, Signal
from .sandbox import simulate_sandbox

_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_REQUIRED_FILES = ("source.json", "pipeline.json", "dashboard.json", "baseline.json")


class IncidentInputError(ValueError):
    """Raised when a fixture target is invalid or incomplete."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncidentInputError(f"Could not read valid JSON fixture: {path.name}") from exc
    if not isinstance(data, dict):
        raise IncidentInputError(f"Fixture must contain a JSON object: {path.name}")
    return data


def _signal(kind: str, severity: str, title: str, metric: str, observed: Any,
            expected: Any, source: str, detail: str) -> Signal:
    stable = hashlib.sha256(f"{kind}|{metric}|{source}|{detail}".encode()).hexdigest()[:16]
    return Signal(
        id=f"sig_{stable}",
        signal_type=kind,
        severity=severity,  # validated by Pydantic
        title=title,
        metric=metric,
        observed=observed,
        expected=expected,
        evidence=[Evidence(source=source, detail=detail)],
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _ensure_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                result_json TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at)")


def analyze_fixture(target: str, fixture_root: str | Path, db_path: str | Path, remediation_mode: str = "dry_run") -> IncidentResult:
    """Analyze one allowlisted fixture directory and persist a JSON run record.

    This function is read-only with respect to fixture files. It does not execute
    remediation plans or invoke arbitrary commands.
    """
    started = time.monotonic()
    if not _TARGET_RE.fullmatch(target) or target in {".", ".."}:
        raise IncidentInputError("Target must be a simple directory name.")

    if remediation_mode not in {"read_only", "dry_run", "sandbox"}:
        raise IncidentInputError("Unsupported remediation mode.")
    root = Path(fixture_root).resolve()
    try:
        documents, source_hashes = FixtureConnector(root).collect(target)
    except ConnectorError as exc:
        raise IncidentInputError(str(exc)) from exc

    source = documents["source.json"]
    pipeline = documents["pipeline.json"]
    dashboard = documents["dashboard.json"]
    baseline = documents["baseline.json"]
    signals: list[Signal] = []

    pipeline_status = str(pipeline.get("status", "unknown")).lower()
    if pipeline_status not in {"success", "succeeded", "ok", "healthy"}:
        signals.append(_signal(
            "pipeline_failure", "high", "Pipeline is not healthy", "pipeline.status",
            pipeline_status, "success", "pipeline.json",
            f"Observed pipeline status: {pipeline_status}",
        ))

    current_schema = source.get("schema")
    expected_schema = baseline.get("schema")
    if isinstance(current_schema, list) and isinstance(expected_schema, list):
        if set(current_schema) != set(expected_schema):
            signals.append(_signal(
                "schema_drift", "high", "Source schema differs from baseline", "source.schema",
                current_schema, expected_schema, "source.json",
                "Compared source schema fields with baseline schema fields.",
            ))

    row_count = source.get("row_count")
    expected_rows = baseline.get("row_count")
    if isinstance(row_count, (int, float)) and isinstance(expected_rows, (int, float)) and expected_rows > 0:
        ratio = row_count / expected_rows
        if ratio < 0.5 or ratio > 1.5:
            signals.append(_signal(
                "volume_anomaly", "medium", "Row count differs materially from baseline",
                "source.row_count", row_count, expected_rows, "source.json",
                f"Current/baseline row-count ratio: {ratio:.3f}",
            ))

    freshness_sla = baseline.get("freshness_sla_hours", 24)
    updated_at = _parse_timestamp(source.get("updated_at"))
    if isinstance(freshness_sla, (int, float)) and freshness_sla >= 0 and updated_at:
        age_hours = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
        if age_hours > freshness_sla:
            signals.append(_signal(
                "stale_data", "high" if age_hours > freshness_sla * 2 else "medium",
                "Source data is outside the freshness SLA", "source.age_hours",
                round(age_hours, 2), freshness_sla, "source.json",
                f"Source timestamp {updated_at.isoformat()} exceeds the configured freshness SLA.",
            ))

    dashboard_time = _parse_timestamp(dashboard.get("updated_at"))
    if updated_at and dashboard_time and dashboard_time < updated_at:
        signals.append(_signal(
            "stale_dashboard", "medium", "Dashboard is older than its source data",
            "dashboard.updated_at", dashboard.get("updated_at"), source.get("updated_at"),
            "dashboard.json", "Dashboard timestamp precedes the source update timestamp.",
        ))

    # Compatibility checks for the inherited RepoSentinel operations fixtures.
    # These remain deterministic observations, not inferred production telemetry.
    age_minutes = source.get("age_minutes")
    freshness_limit = source.get("freshness_sla_minutes")
    if isinstance(age_minutes, (int, float)) and isinstance(freshness_limit, (int, float)) and age_minutes > freshness_limit:
        signals.append(_signal(
            "stale_data", "high" if age_minutes > freshness_limit * 2 else "medium",
            "Source age exceeds its freshness SLA", "source.age_minutes",
            age_minutes, freshness_limit, "source.json",
            "Compared fixture source age with freshness_sla_minutes.",
        ))

    dashboard_age = dashboard.get("age_minutes")
    dashboard_limit = dashboard.get("expected_max_age_minutes")
    if isinstance(dashboard_age, (int, float)) and isinstance(dashboard_limit, (int, float)) and dashboard_age > dashboard_limit:
        signals.append(_signal(
            "stale_dashboard", "high" if dashboard_age > dashboard_limit * 2 else "medium",
            "Dashboard age exceeds its freshness limit", "dashboard.age_minutes",
            dashboard_age, dashboard_limit, "dashboard.json",
            "Compared dashboard age with expected_max_age_minutes.",
        ))

    source_metrics = source.get("metrics")
    dashboard_metrics = dashboard.get("metrics")
    if isinstance(source_metrics, dict) and isinstance(dashboard_metrics, dict) and source_metrics != dashboard_metrics:
        signals.append(_signal(
            "dashboard_mismatch", "high", "Dashboard metrics differ from source metrics",
            "dashboard.metrics", dashboard_metrics, source_metrics, "dashboard.json",
            "Compared the dashboard metric snapshot with the source metric snapshot.",
        ))

    null_rates = source.get("null_rates")
    baseline_null_rates = baseline.get("null_rates")
    if isinstance(null_rates, dict) and isinstance(baseline_null_rates, dict):
        for column, observed_rate in null_rates.items():
            expected_rate = baseline_null_rates.get(column)
            if isinstance(observed_rate, (int, float)) and isinstance(expected_rate, (int, float)):
                if observed_rate > max(expected_rate * 3, expected_rate + 0.05):
                    signals.append(_signal(
                        "null_rate_spike", "high", f"Null rate increased for {column}",
                        f"source.null_rates.{column}", observed_rate, expected_rate, "source.json",
                        f"Observed null rate is materially above the baseline for {column}.",
                    ))

    duration = pipeline.get("duration_minutes")
    duration_limit = baseline.get("pipeline_duration_slo_minutes")
    if isinstance(duration, (int, float)) and isinstance(duration_limit, (int, float)) and duration > duration_limit:
        signals.append(_signal(
            "slow_pipeline", "medium" if duration <= duration_limit * 2 else "high",
            "Pipeline duration exceeds its SLO", "pipeline.duration_minutes",
            duration, duration_limit, "pipeline.json",
            "Compared pipeline duration with pipeline_duration_slo_minutes.",
        ))

    hypotheses: list[Hypothesis] = []
    by_type = {s.signal_type: s for s in signals}
    if "pipeline_failure" in by_type:
        hypotheses.append(Hypothesis(
            title="Pipeline execution failure",
            explanation="The pipeline fixture reports a non-success state. Inspect its recorded error and upstream dependencies.",
            confidence=0.75, supporting_signal_ids=[by_type["pipeline_failure"].id],
        ))
    if "schema_drift" in by_type:
        hypotheses.append(Hypothesis(
            title="Upstream schema change",
            explanation="Source fields differ from the declared baseline. Downstream transformations may require a reviewed schema update.",
            confidence=0.85, supporting_signal_ids=[by_type["schema_drift"].id],
        ))
    if "stale_data" in by_type:
        hypotheses.append(Hypothesis(
            title="Delayed or stalled data ingestion",
            explanation="The source age exceeds its configured freshness SLA. Check upstream arrival and pipeline scheduling.",
            confidence=0.7, supporting_signal_ids=[by_type["stale_data"].id],
        ))
    if "dashboard_mismatch" in by_type:
        hypotheses.append(Hypothesis(
            title="Dashboard snapshot is inconsistent with source metrics",
            explanation="The recorded dashboard metric snapshot differs from the source fixture. Review refresh scheduling and transformation lineage.",
            confidence=0.8, supporting_signal_ids=[by_type["dashboard_mismatch"].id],
        ))
    if "null_rate_spike" in by_type:
        matching = [signal.id for signal in signals if signal.signal_type == "null_rate_spike"]
        hypotheses.append(Hypothesis(
            title="Upstream data quality regression",
            explanation="One or more source null rates materially exceed their configured baseline.",
            confidence=0.75, supporting_signal_ids=matching,
        ))
    if "slow_pipeline" in by_type:
        hypotheses.append(Hypothesis(
            title="Pipeline performance regression",
            explanation="Recorded pipeline duration exceeds the fixture's configured SLO. Inspect upstream waits and expensive transformation stages.",
            confidence=0.65, supporting_signal_ids=[by_type["slow_pipeline"].id],
        ))
    if not hypotheses and signals:
        hypotheses.append(Hypothesis(
            title="Multiple data reliability signals require triage",
            explanation="Several deterministic checks raised signals. Review their evidence before selecting a root cause.",
            confidence=0.5, supporting_signal_ids=[s.id for s in signals],
        ))

    plans: list[RemediationPlan] = []
    if signals:
        plans.append(RemediationPlan(
            title="Review evidence and validate a recovery plan",
            rationale="OpsPilot AI does not execute production changes. Confirm the cause, prepare a change in an isolated environment, and rerun validation.",
            mode="dry_run",
            requires_human_review=True,
            validation_checks=[
                "Confirm pipeline status is successful",
                "Compare source schema with the approved contract",
                "Check row counts against the accepted baseline",
                "Confirm source and dashboard freshness",
            ],
        ))

    now = datetime.now(timezone.utc)
    result = IncidentResult(
        run_id=str(uuid4()),
        target=target,
        status="completed",
        created_at=now,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        signals=signals,
        hypotheses=hypotheses,
        remediation_plans=plans,
        summary=(f"Detected {len(signals)} reliability signal(s)." if signals
                 else "No configured reliability checks were triggered."),
        source_hashes=source_hashes,
        sandbox_result=(simulate_sandbox(target, root) if remediation_mode == "sandbox" else None),
    )
    database = Path(db_path).resolve()
    _ensure_database(database)
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO runs(run_id, target, status, created_at, result_json) VALUES (?, ?, ?, ?, ?)",
            (result.run_id, result.target, result.status, result.created_at.isoformat(),
             result.model_dump_json()),
        )
    return result


def get_run(run_id: str, db_path: str | Path) -> IncidentResult | None:
    database = Path(db_path).resolve()
    if not database.exists():
        return None
    with sqlite3.connect(database) as conn:
        row = conn.execute("SELECT result_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return IncidentResult.model_validate_json(row[0]) if row else None


def list_runs(db_path: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    database = Path(db_path).resolve()
    if not database.exists():
        return []
    with sqlite3.connect(database) as conn:
        rows = conn.execute(
            "SELECT run_id, target, status, created_at FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"run_id": row[0], "target": row[1], "status": row[2], "created_at": row[3]}
        for row in rows
    ]
