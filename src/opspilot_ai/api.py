"""FastAPI endpoints for local OpsPilot AI incident runs."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import __version__
from .approvals import ApprovalError, create_approval, decide_approval, get_approval, verify_approval_events
from .audit import verify_audit_chain
from .auth import Principal, require_any_permission, require_permission
from .idempotency import IdempotencyConflict, complete as complete_idempotency, release as release_idempotency, reserve as reserve_idempotency
from .observability import summarize_runs
from .service import IncidentInputError, analyze_fixture, get_run, list_runs

FIXTURE_ROOT = Path(os.getenv("OPSPILOT_FIXTURE_ROOT", "examples/ops_cases")).resolve()
DB_PATH = Path(os.getenv("OPSPILOT_DB_PATH", ".opspilot/opspilot.sqlite3")).resolve()

app = FastAPI(
    title="OpsPilot AI API",
    version=__version__,
    description="Local-first, fixture-backed data reliability investigation. No production writes.",
)


class RunRequest(BaseModel):
    target: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    connector: Literal["fixture"] = "fixture"
    mode: Literal["analyze"] = "analyze"
    remediation_mode: Literal["read_only", "dry_run", "sandbox"] = "dry_run"


class ApprovalRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=8, max_length=1000)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "opspilot-ai", "api_version": "v1", "version": __version__}


@app.post("/api/v1/runs", status_code=201)
def create_run(
    request: RunRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _principal: Principal = Depends(require_permission("run")),
):
    reservation = None
    if idempotency_key is not None:
        try:
            reservation = reserve_idempotency(DB_PATH, f"{_principal.actor}:{idempotency_key}", request.model_dump(mode="json"))
            if reservation["state"] == "replay":
                return reservation["response"]
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        result = analyze_fixture(request.target, FIXTURE_ROOT, DB_PATH, request.remediation_mode)
        payload = result.model_dump(mode="json")
        if reservation is not None:
            complete_idempotency(DB_PATH, reservation, payload)
        return payload
    except IncidentInputError as exc:
        if reservation is not None:
            release_idempotency(DB_PATH, reservation)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        if reservation is not None:
            release_idempotency(DB_PATH, reservation)
        raise


@app.get("/api/v1/runs")
def runs(
    limit: int = Query(default=20, ge=1, le=100),
    _principal: Principal = Depends(require_permission("read")),
):
    return {"items": list_runs(DB_PATH, limit=limit)}


@app.get("/api/v1/runs/{run_id}")
def run_detail(run_id: str, _principal: Principal = Depends(require_permission("read"))):
    result = get_run(run_id, DB_PATH)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@app.get("/api/v1/runs/{run_id}/report")
def run_report(run_id: str, _principal: Principal = Depends(require_permission("read"))):
    result = get_run(run_id, DB_PATH)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": result.run_id,
        "target": result.target,
        "summary": result.summary,
        "source_hashes": result.source_hashes,
        "sandbox_result": result.sandbox_result,
        "lifecycle_events": result.lifecycle_events,
        "triage": result.triage,
        "policy_decision": result.policy_decision,
        "agent_workflow": result.agent_workflow,
        "audit_chain: result.audit_chain,
        "signals": [signal.model_dump() for signal in result.signals],
        "hypotheses": [hypothesis.model_dump() for hypothesis in result.hypotheses],
        "remediation_plans": [plan.model_dump() for plan in result.remediation_plans],
    }


@app.get("/api/v1/runs/{run_id}/audit/verify")
def verify_run_audit(run_id: str, _principal: Principal = Depends(require_permission("read"))):
    result = get_run(run_id, DB_PATH)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return verify_audit_chain(result.audit_chain)


@app.post("/api/v1/runs/{run_id}/approvals", status_code=201)
def request_approval(
    run_id: str,
    request: ApprovalRequest,
    principal: Principal = Depends(require_permission("request_approval")),
):
    result = get_run(run_id, DB_PATH)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        return create_approval(DB_PATH, run_id, principal.actor, request.reason, result)
    except ApprovalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/approvals/{approval_id}")
def approval_detail(approval_id: str, _principal: Principal = Depends(require_permission("read"))):
    result = get_approval(DB_PATH, approval_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return result


@app.get("/api/v1/approvals/{approval_id}/audit/verify")
def verify_approval_audit(approval_id: str, _principal: Principal = Depends(require_permission("read"))):
    result = get_approval(DB_PATH, approval_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return verify_approval_events(result)


@app.post("/api/v1/approvals/{approval_id}/decision")
def approval_decision(
    approval_id: str,
    request: ApprovalDecisionRequest,
    principal: Principal = Depends(require_any_permission("decide_approval")),
):
    try:
        return decide_approval(DB_PATH, approval_id, principal.actor, request.decision, request.reason)
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/metrics")
def metrics(_principal: Principal = Depends(require_permission("read"))):
    recent = list_runs(DB_PATH, limit=100)
    results = [get_run(item["run_id"], DB_PATH) for item in recent]
    return summarize_runs([result for result in results if result is not None])
