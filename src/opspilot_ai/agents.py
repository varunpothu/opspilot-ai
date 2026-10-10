"""Bounded, deterministic multi-agent workflow for evidence-first incident investigation.

These agents are deliberately not LLM-backed and have no tool-execution privileges.
They provide a tested orchestration seam for future model-assisted investigation.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .policy import evaluate_run_policy
from .triage import assess_incident

MAX_SIGNALS = 500
MAX_WORKFLOW_STEPS = 8


@dataclass
class AgentContext:
    target: str
    signals: list[Any]
    remediation_mode: str = "read_only"
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentEvent:
    agent: str
    status: str
    duration_ms: int
    output_digest: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class AgentWorkflowResult:
    status: str
    target: str
    evidence_digest: str | None
    triage: dict[str, Any] | None
    policy_decision: dict[str, Any] | None
    recommendations: tuple[str, ...]
    events: tuple[AgentEvent, ...]
    execution_performed: bool = False


class AgentStep(Protocol):
    name: str

    def run(self, context: AgentContext) -> dict[str, Any]: ...


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _signal_dict(signal: Any) -> dict[str, Any]:
    if hasattr(signal, "model_dump"):
        return signal.model_dump(mode="json")
    if isinstance(signal, dict):
        return signal
    raise TypeError("each signal must be a typed model or dictionary")


class EvidenceValidationAgent:
    name = "evidence-validation"

    def run(self, context: AgentContext) -> dict[str, Any]:
        if not context.target or len(context.target) > 80:
            raise ValueError("invalid_target")
        if len(context.signals) > MAX_SIGNALS:
            raise ValueError("signal_limit_exceeded")
        serialized = [_signal_dict(signal) for signal in context.signals]
        identifiers = [item.get("id") for item in serialized]
        if any(not isinstance(item, str) or not item for item in identifiers):
            raise ValueError("signal_id_missing")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate_signal_id")
        for item in serialized:
            if not isinstance(item.get("evidence", []), list):
                raise ValueError("invalid_evidence_shape")
        digest = hashlib.sha256(_canonical(serialized)).hexdigest()
        context.state["signals_json"] = serialized
        context.state["evidence_digest"] = digest
        return {"evidence_digest": digest, "signal_count": len(serialized)}


class IncidentTriageAgent:
    name = "incident-triage"

    def run(self, context: AgentContext) -> dict[str, Any]:
        triage = assess_incident(context.target, context.signals)
        context.state["triage"] = triage
        return triage


class PolicyGateAgent:
    name = "policy-gate"

    def run(self, context: AgentContext) -> dict[str, Any]:
        decision = evaluate_run_policy(context.signals, context.remediation_mode)
        # Defence in depth: policy outputs that imply execution fail closed.
        if decision.get("execution_permitted") is not False or decision.get("production_writes_permitted") is not False:
            raise ValueError("policy_execution_invariant_failed")
        context.state["policy_decision"] = decision
        return decision


class RecommendationAgent:
    name = "recommendation-planner"

    def run(self, context: AgentContext) -> dict[str, Any]:
        triage = context.state["triage"]
        policy = context.state["policy_decision"]
        recommendations = list(triage["recommended_next_steps"])
        recommendations.append("Treat all findings as evidence-backed hypotheses; validate source lineage before changing a system.")
        if policy.get("human_approval_required"):
            recommendations.append("Human review is required; no remediation has been executed.")
        context.state["recommendations"] = recommendations
        return {"recommendations": recommendations, "execution_performed": False}


class SafetyEvaluationAgent:
    name = "safety-evaluator"

    def run(self, context: AgentContext) -> dict[str, Any]:
        policy = context.state["policy_decision"]
        recommendations = context.state["recommendations"]
        if policy.get("decision") == "deny":
            raise ValueError("policy_denied")
        if policy.get("execution_permitted") or policy.get("production_writes_permitted"):
            raise ValueError("unsafe_policy_result")
        if any("execute remediation now" in item.lower() for item in recommendations):
            raise ValueError("unsafe_recommendation")
        return {"checks_passed": ["policy_default_deny", "no_production_writes", "review_only_recommendations"]}


class AgentWorkflow:
    """Execute a fixed, bounded agent graph; never executes actions or dynamic tools."""

    def __init__(self, agents: tuple[AgentStep, ...] | None = None):
        self.agents = agents or (
            EvidenceValidationAgent(),
            IncidentTriageAgent(),
            PolicyGateAgent(),
            RecommendationAgent(),
            SafetyEvaluationAgent(),
        )
        if not self.agents or len(self.agents) > MAX_WORKFLOW_STEPS:
            raise ValueError(f"workflow must contain 1 to {MAX_WORKFLOW_STEPS} steps")
        names = [agent.name for agent in self.agents]
        if len(names) != len(set(names)):
            raise ValueError("agent names must be unique")

    def run(
        self, target: str, signals: list[Any], remediation_mode: str = "read_only",
    ) -> AgentWorkflowResult:
        context = AgentContext(target=target, signals=signals, remediation_mode=remediation_mode)
        events: list[AgentEvent] = []
        status = "completed"
        for agent in self.agents:
            started = time.perf_counter()
            try:
                output = agent.run(context)
                digest = hashlib.sha256(_canonical(output)).hexdigest()
                events.append(AgentEvent(
                    agent=agent.name, status="succeeded",
                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    output_digest=digest,
                ))
            except Exception as exc:
                # Error details are reduced to a code to avoid logging source payloads/secrets.
                code = str(exc)[:80] if isinstance(exc, ValueError) else "agent_step_failed"
                events.append(AgentEvent(
                    agent=agent.name, status="failed",
                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    error_code=code,
                ))
                status = "failed"
                break
        return AgentWorkflowResult(
            status=status,
            target=target,
            evidence_digest=context.state.get("evidence_digest"),
            triage=context.state.get("triage"),
            policy_decision=context.state.get("policy_decision"),
            recommendations=tuple(context.state.get("recommendations", [])),
            events=tuple(events),
            execution_performed=False,
        )
