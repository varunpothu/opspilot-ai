"""FastAPI endpoints for local OpsPilot AI incident runs."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import __version__
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
    remediation_mode: Literal["read_only", "dry_run"] = "dry_run"


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "opspilot-ai", "api_version": "v1", "version": __version__}


@app.post("/api/v1/runs", status_code=201)
def create_run(request: RunRequest):
    try:
        return analyze_fixture(request.target, FIXTURE_ROOT, DB_PATH)
    except IncidentInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/runs")
def runs(limit: int = Query(default=20, ge=1, le=100)):
    return {"items": list_runs(DB_PATH, limit=limit)}


@app.get("/api/v1/runs/{run_id}")
def run_detail(run_id: str):
    result = get_run(run_id, DB_PATH)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@app.get("/api/v1/runs/{run_id}/report")
def run_report(run_id: str):
    result = get_run(run_id, DB_PATH)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": result.run_id,
        "target": result.target,
        "summary": result.summary,
        "signals": [signal.model_dump() for signal in result.signals],
        "hypotheses": [hypothesis.model_dump() for hypothesis in result.hypotheses],
        "remediation_plans": [plan.model_dump() for plan in result.remediation_plans],
    }
