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
    assert [event["status"] for event in result.lifecycle_events] == ["running", "succeeded"]
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



def test_sandbox_mode_returns_validation_and_provenance(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    target = write_fixture(fixtures, "sandbox_case")
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    result = analyze_fixture("sandbox_case", fixtures, tmp_path / "runs.sqlite3", "sandbox")

    assert result.sandbox_result is not None
    assert result.sandbox_result["status"] == "passed"
    assert result.sandbox_result["original_files_unchanged"] is True
    assert set(result.source_hashes) == {
        "source.json", "pipeline.json", "dashboard.json", "baseline.json"
    }
    assert before == {p.name: p.read_bytes() for p in target.iterdir()}


def test_api_sandbox_mode_is_available(tmp_path: Path, monkeypatch) -> None:
    import opspilot_ai.api as api_module

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    write_fixture(fixtures, "sandbox_api")
    monkeypatch.setattr(api_module, "FIXTURE_ROOT", fixtures)
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "runs.sqlite3")
    client = TestClient(api_module.app)
    response = client.post("/api/v1/runs", json={
        "target": "sandbox_api",
        "connector": "fixture",
        "mode": "analyze",
        "remediation_mode": "sandbox",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["sandbox_result"]["status"] == "passed"
    assert body["sandbox_result"]["production_writes"] == 0
    assert body["source_hashes"]


def test_failed_sandbox_validation_fails_the_run(tmp_path: Path, monkeypatch) -> None:
    import opspilot_ai.service as service_module

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    write_fixture(fixtures, "failed_sandbox")
    monkeypatch.setattr(service_module, "simulate_sandbox", lambda *_: {
        "mode": "sandbox",
        "status": "failed",
        "checks": {"postcondition": False},
        "original_files_unchanged": True,
        "production_writes": 0,
        "executed_commands": [],
    })
    result = analyze_fixture("failed_sandbox", fixtures, tmp_path / "failed.sqlite3", "sandbox")
    assert result.status == "failed"
    assert result.lifecycle_events[-1]["status"] == "failed"
    assert "validation failed" in result.summary


def test_api_audit_verification_and_policy_report(tmp_path: Path, monkeypatch) -> None:
    import opspilot_ai.api as api_module

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    write_fixture(fixtures, "audit_api")
    monkeypatch.setattr(api_module, "FIXTURE_ROOT", fixtures)
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "audit.sqlite3")
    client = TestClient(api_module.app)
    created = client.post("/api/v1/runs", json={"target": "audit_api", "remediation_mode": "read_only"})
    assert created.status_code == 201
    body = created.json()
    assert body["policy_decision"]["execution_permitted"] is False
    assert body["triage"]["incident_fingerprint"]
    assert body["audit_chain"]
    run_id = body["run_id"]
    verified = client.get(f"/api/v1/runs/{run_id}/audit/verify")
    assert verified.status_code == 200
    assert verified.json()["valid"] is True
    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["policy_decision"]["production_writes_permitted"] is False


def test_api_metrics_endpoint_returns_bounded_summary(tmp_path: Path, monkeypatch) -> None:
    import opspilot_ai.api as api_module

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    write_fixture(fixtures, "metrics_api")
    monkeypatch.setattr(api_module, "FIXTURE_ROOT", fixtures)
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "metrics.sqlite3")
    client = TestClient(api_module.app)
    created = client.post("/api/v1/runs", json={"target": "metrics_api", "remediation_mode": "read_only"})
    assert created.status_code == 201
    metrics = client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["sample_size"] == 1
    assert body["run_status_counts"] == {"completed": 1}
    assert "limitations" in body
