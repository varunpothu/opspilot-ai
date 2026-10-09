from __future__ import annotations

import json
from pathlib import Path

import pytest

from opspilot_ai.connectors import ConnectorError, FixtureConnector
from opspilot_ai.lifecycle import RunLifecycle, RunStatus
from opspilot_ai.sandbox import simulate_sandbox


def make_fixture(root: Path, target: str = "sample") -> Path:
    directory = root / target
    directory.mkdir(parents=True)
    values = {
        "source.json": {"updated_at": "2026-10-09T10:00:00Z", "schema": ["id", "new_col"], "row_count": 90},
        "pipeline.json": {"status": "failed", "error": "timeout"},
        "dashboard.json": {"updated_at": "2026-10-09T09:00:00Z"},
        "baseline.json": {"schema": ["id"], "row_count": 100, "freshness_sla_hours": 24},
    }
    for name, value in values.items():
        (directory / name).write_text(json.dumps(value), encoding="utf-8")
    return directory


def test_lifecycle_rejects_illegal_terminal_transition() -> None:
    lifecycle = RunLifecycle()
    lifecycle.transition(RunStatus.RUNNING, "analysis started")
    lifecycle.transition(RunStatus.SUCCEEDED, "analysis completed")
    with pytest.raises(ValueError):
        lifecycle.transition(RunStatus.RUNNING, "cannot restart a completed run")
    assert [event.status for event in lifecycle.events] == [RunStatus.RUNNING, RunStatus.SUCCEEDED]


def test_fixture_connector_returns_sha256_and_is_read_only(tmp_path: Path) -> None:
    target = make_fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    documents, hashes = FixtureConnector(tmp_path).collect("sample")
    assert set(documents) == {"source.json", "pipeline.json", "dashboard.json", "baseline.json"}
    assert all(len(value) == 64 for value in hashes.values())
    assert before == {p.name: p.read_bytes() for p in target.iterdir()}


def test_connector_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ConnectorError):
        FixtureConnector(tmp_path).collect("../outside")


def test_sandbox_repairs_only_copy_and_validates(tmp_path: Path) -> None:
    target = make_fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    result = simulate_sandbox("sample", tmp_path)
    assert result["status"] == "passed"
    assert result["original_files_unchanged"] is True
    assert result["executed_commands"] == []
    assert result["production_writes"] == 0
    assert all(result["checks"].values())
    assert before == {p.name: p.read_bytes() for p in target.iterdir()}


def test_sandbox_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "source.json").write_text("{}", encoding="utf-8")
    (root / "escape").mkdir()
    (root / "escape" / "source.json").symlink_to(outside / "source.json")
    with pytest.raises(ConnectorError):
        FixtureConnector(root).collect("escape")


def test_all_ten_inherited_fixture_scenarios_cover_distinct_signals(tmp_path: Path) -> None:
    import shutil

    fixtures = Path(__file__).parents[1] / "examples" / "ops_cases"
    expected = {
        "01_pipeline_failure_stale_dashboard": {"pipeline_failure", "dashboard_mismatch", "stale_dashboard"},
        "02_schema_drift": {"schema_drift"},
        "03_null_spike": {"null_rate_spike"},
        "04_dashboard_mismatch": {"dashboard_mismatch"},
        "05_freshness_sla": {"stale_data", "stale_dashboard", "slow_pipeline"},
        "06_volume_drop": {"volume_anomaly"},
        "07_multiple_incident": {"pipeline_failure", "schema_drift", "null_rate_spike", "volume_anomaly"},
        "08_healthy": set(),
        "09_slow_pipeline": {"slow_pipeline"},
        "10_dashboard_stale_only": {"stale_dashboard"},
    }
    from opspilot_ai.service import analyze_fixture

    for case, expected_types in expected.items():
        result = analyze_fixture(case, fixtures, tmp_path / f"{case}.sqlite3")
        observed = {signal.signal_type for signal in result.signals}
        assert expected_types <= observed
        if case == "08_healthy":
            assert observed == set()


def test_inherited_fixture_sandbox_repairs_dashboard_on_copy(tmp_path: Path) -> None:
    import shutil

    fixtures = Path(__file__).parents[1] / "examples" / "ops_cases"
    original = fixtures / "01_pipeline_failure_stale_dashboard"
    copied_root = tmp_path / "fixtures"
    copied_root.mkdir()
    copied_case = copied_root / original.name
    shutil.copytree(original, copied_case)
    before = {p.name: p.read_bytes() for p in copied_case.iterdir()}

    result = simulate_sandbox(original.name, copied_root)

    assert result["status"] == "passed"
    assert result["original_files_unchanged"] is True
    assert result["checks"]["dashboard_metrics_match_source"] is True
    assert result["checks"]["dashboard_within_age_limit"] is True
    assert before == {p.name: p.read_bytes() for p in copied_case.iterdir()}
