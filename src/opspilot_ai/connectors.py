"""Allowlisted, read-only fixture connector used by the local MVP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_FIXTURES = ("source.json", "pipeline.json", "dashboard.json", "baseline.json")
MAX_FIXTURE_BYTES = 1_000_000


class ConnectorError(ValueError):
    """Input could not be safely collected from the configured fixture root."""


class FixtureConnector:
    name = "fixture"
    capabilities = ("read", "hash", "evidence")
    writable = False

    def __init__(self, fixture_root: str | Path):
        self.root = Path(fixture_root).resolve()

    def collect(self, target: str) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        if not target or target in {".", ".."} or "/" in target or "\\" in target:
            raise ConnectorError("Target must be a single fixture directory name.")
        directory = (self.root / target).resolve()
        if self.root not in directory.parents or not directory.is_dir():
            raise ConnectorError("Target is missing or outside the configured fixture root.")

        documents: dict[str, dict[str, Any]] = {}
        hashes: dict[str, str] = {}
        for filename in REQUIRED_FIXTURES:
            path = (directory / filename).resolve()
            if directory not in path.parents or not path.is_file():
                raise ConnectorError(f"Missing or unsafe fixture: {filename}")
            if path.stat().st_size > MAX_FIXTURE_BYTES:
                raise ConnectorError(f"Fixture exceeds the {MAX_FIXTURE_BYTES}-byte size limit: {filename}")
            raw = path.read_bytes()
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ConnectorError(f"Fixture is not valid UTF-8 JSON: {filename}") from exc
            if not isinstance(parsed, dict):
                raise ConnectorError(f"Fixture must contain a JSON object: {filename}")
            documents[filename] = parsed
            hashes[filename] = hashlib.sha256(raw).hexdigest()
        return documents, hashes
