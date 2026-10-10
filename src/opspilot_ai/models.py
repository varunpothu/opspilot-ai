"""Typed contracts shared by the OpsPilot AI service and API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Evidence(BaseModel):
    source: str
    detail: str
    observed_at: datetime = Field(default_factory=utc_now)


class Signal(BaseModel):
    id: str
    signal_type: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    title: str
    metric: str
    observed: Any = None
    expected: Any = None
    evidence: list[Evidence] = Field(default_factory=list)
    detector: str = "fixture-detector"
    detector_version: str = "0.1.0"


class Hypothesis(BaseModel):
    title: str
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_signal_ids: list[str] = Field(default_factory=list)
    status: Literal["candidate", "supported", "rejected", "unresolved"] = "candidate"


class RemediationPlan(BaseModel):
    title: str
    rationale: str
    mode: Literal["read_only", "dry_run"] = "dry_run"
    requires_human_review: bool = True
    execution_status: Literal["not_executed"] = "not_executed"
    validation_checks: list[str] = Field(default_factory=list)


class IncidentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    run_id: str
    target: str
    status: Literal["completed", "failed"]
    created_at: datetime
    duration_ms: int
    signals: list[Signal] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    remediation_plans: list[RemediationPlan] = Field(default_factory=list)
    summary: str
    source_hashes: dict[str, str] = Field(default_factory=dict)
    sandbox_result: dict[str, Any] | None = None
    lifecycle_events: list[dict[str, Any]] = Field(default_factory=list)
    triage: dict[str, Any] = Field(default_factory=dict)
    policy_decision: dict[str, Any] = Field(default_factory=dict)
    agent_workflow: dict[str, Any] = Field(default_factory=dict)
    audit_chain: list[dict[str, Any]] = Field(default_factory=list)
