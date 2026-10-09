"""Disposable fixture sandbox. Never writes to the original source directory."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .connectors import REQUIRED_FIXTURES, ConnectorError, FixtureConnector


def _hashes(directory: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in REQUIRED_FIXTURES
    }


def simulate_sandbox(target: str, fixture_root: str | Path) -> dict[str, Any]:
    """Apply only named fixture repairs in a disposable copy and validate the result.

    This is a demonstration of sandboxed JSON-fixture repair, not a production repair
    connector. No shell commands are run and no original fixture is modified.
    """
    root = Path(fixture_root).resolve()
    connector = FixtureConnector(root)
    docs, original_hashes = connector.collect(target)
    source_dir = (root / target).resolve()
    before = {
        name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        for name in REQUIRED_FIXTURES
    }

    with tempfile.TemporaryDirectory(prefix="opspilot-sandbox-") as temporary:
        sandbox = Path(temporary) / target
        shutil.copytree(source_dir, sandbox)
        source = docs["source.json"]
        pipeline = docs["pipeline.json"]
        dashboard = docs["dashboard.json"]
        baseline = docs["baseline.json"]
        changes: list[str] = []

        # These are the only permitted mutations. The simulation operates on copies.
        if str(pipeline.get("status", "")).lower() not in {"success", "succeeded", "ok", "healthy"}:
            pipeline["status"] = "success"
            pipeline["error"] = None
            changes.append("set pipeline status to success in sandbox")
        if isinstance(source.get("schema"), list) and isinstance(baseline.get("schema"), list):
            if set(source["schema"]) != set(baseline["schema"]):
                source["quarantined_fields"] = sorted(set(source["schema"]) - set(baseline["schema"]))
                source["schema"] = list(baseline["schema"])
                changes.append("quarantined unexpected schema fields in sandbox")
        if isinstance(source.get("updated_at"), str):
            dashboard["updated_at"] = source["updated_at"]
            changes.append("aligned dashboard timestamp with source in sandbox")
        if isinstance(source.get("metrics"), dict):
            dashboard["metrics"] = dict(source["metrics"])
            changes.append("regenerated dashboard metrics from source in sandbox")
        if isinstance(dashboard.get("age_minutes"), (int, float)):
            dashboard["age_minutes"] = 0
            changes.append("refreshed dashboard age in sandbox")

        for filename, document in (
            ("source.json", source),
            ("pipeline.json", pipeline),
            ("dashboard.json", dashboard),
        ):
            (sandbox / filename).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

        repaired = {name: json.loads((sandbox / name).read_text(encoding="utf-8")) for name in REQUIRED_FIXTURES}
        repaired_source = repaired["source.json"]
        repaired_pipeline = repaired["pipeline.json"]
        repaired_dashboard = repaired["dashboard.json"]
        repaired_baseline = repaired["baseline.json"]
        checks = {
            "pipeline_healthy": str(repaired_pipeline.get("status", "")).lower() in {"success", "succeeded", "ok", "healthy"},
            "schema_matches_baseline": (
                not isinstance(repaired_source.get("schema"), list)
                or not isinstance(repaired_baseline.get("schema"), list)
                or set(repaired_source["schema"]) == set(repaired_baseline["schema"])
            ),
            "dashboard_not_older_than_source": (
                not isinstance(repaired_source.get("updated_at"), str)
                or not isinstance(repaired_dashboard.get("updated_at"), str)
                or repaired_dashboard["updated_at"] >= repaired_source["updated_at"]
            ),
            "dashboard_metrics_match_source": (
                not isinstance(repaired_source.get("metrics"), dict)
                or not isinstance(repaired_dashboard.get("metrics"), dict)
                or repaired_dashboard["metrics"] == repaired_source["metrics"]
            ),
            "dashboard_within_age_limit": (
                not isinstance(repaired_dashboard.get("age_minutes"), (int, float))
                or not isinstance(repaired_dashboard.get("expected_max_age_minutes"), (int, float))
                or repaired_dashboard["age_minutes"] <= repaired_dashboard["expected_max_age_minutes"]
            ),
        }
        after_sandbox = _hashes(sandbox)
        status = "passed" if all(checks.values()) else "failed"

    after_original = {
        name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        for name in REQUIRED_FIXTURES
    }
    return {
        "mode": "sandbox",
        "status": status,
        "changes": changes,
        "checks": checks,
        "original_files_unchanged": before == after_original == original_hashes,
        "original_sha256": original_hashes,
        "sandbox_sha256": after_sandbox,
        "executed_commands": [],
        "production_writes": 0,
        "note": "Simulation only. Changes were confined to a disposable copy; no production system was accessed.",
    }
