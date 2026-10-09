from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from opspilot_ai.api import app
from opspilot_ai.service import IncidentInputError, analyze_fixture, get_run, list_runs


def write_fixture(root: Path, name: str = "sample", *, status: str = "failed") -> Path:
    target = root / name
    target.mkdir(parents=True)
    (target / "source.json").write_text(json.dumps({
        "updated_at": "2020-01-01T00:00:00Z",
        "row_count": 200,
        "schema": ["id", "new_field"],
    }), encoding="utf-8")
    (target / "pipeline.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    (target / "dashboard.json").write_text(json.dumps({
        "updated_at": "2019-12-31T00:00:00Z"
    }), encoding="utf-8")
    (target / "baseline.json").write_text(json.dumps({
        "schema": ["id"], "row_count": 100, "freshness_sla_hours": 24
    }), encoding="utf-8")
    return target


def test_analysis_detects_incident_and_persists_run(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    target = write_fixture(fixtures)
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    db = tmp_path / "runs.sqlite3"

    result = analyze_fixture("sample", fixtures, db)

    assert result.status == "completed"
    assert {signal.signal_type for signal in result.signals} >= {
        "pipeline_failure", "schema_drift", "volume_anomaly", "stale_data", "stale_dashboard"
    }
    assert result.hypotheses
    assert result.remediation_plans
    assert get_run(result.run_id, db).run_id == result.run_id
    assert list_runs(db)[0]["run_id"] == result.run_id
    assert before == {p.name: p.read_bytes() for p in target.iterdir()}


def test_target_traversal_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    try:
        analyze_fixture("../outside", root, tmp_path / "db.sqlite3")
    except IncidentInputError:
        pass
    else:
        raise AssertionError("Traversal target was accepted")


def test_missing_fixture_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    try:
        analyze_fixture("missing", root, tmp_path / "db.sqlite3")
    except IncidentInputError:
        pass
    else:
        raise AssertionError("Missing target was accepted")


def test_api_health() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["service"] == "opspilot-ai"



def test_api_run_lifecycle_with_temporary_database(tmp_path: Path, monkeypatch) -> None:
    import opspilot_ai.api as api_module

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    write_fixture(fixtures, "api_sample")
    monkeypatch.setattr(api_module, "FIXTURE_ROOT", fixtures)
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "api.sqlite3")
    client = TestClient(api_module.app)

    created = client.post("/api/v1/runs", json={
        "target": "api_sample",
        "connector": "fixture",
        "mode": "analyze",
        "remediation_mode": "dry_run",
    })
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    detail = client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["target"] == "api_sample"

    report = client.get(f"/api/v1/runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["run_id"] == run_id

    listing = client.get("/api/v1/runs")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["run_id"] == run_id


def test_api_rejects_unsupported_connector() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/runs", json={
        "target": "demo_warehouse",
        "connector": "production",
        "mode": "analyze",
        "remediation_mode": "dry_run",
    })
    assert response.status_code == 422
