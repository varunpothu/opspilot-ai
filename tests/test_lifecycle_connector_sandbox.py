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
