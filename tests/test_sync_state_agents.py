from __future__ import annotations

import json
import urllib.error
from datetime import timedelta
from email.message import Message

import pytest
from fastapi.testclient import TestClient

from opspilot_ai.agents import AgentWorkflow
from opspilot_ai.api import app
from opspilot_ai.http_connector import ConditionalHTTPConnector, ReadOnlyHTTPError
from opspilot_ai.incremental import IncrementalSyncError, IncrementalSyncRunner
from opspilot_ai.models import Evidence, Signal
from opspilot_ai.sync_state import CheckpointConflict, SyncStateStore, WatermarkRegression


def _signal(signal_id: str = "sig-1") -> Signal:
    return Signal(
        id=signal_id, signal_type="pipeline_failure", severity="high",
        title="Pipeline failed", metric="pipeline.status", observed="failed",
        expected="success", evidence=[Evidence(source="pipeline.json", detail="Fixture reports failed")],
    )


def test_watermark_checkpoint_is_monotonic_and_compare_and_swap(tmp_path):
    store = SyncStateStore(tmp_path / "sync.sqlite3")
    first = store.commit_checkpoint(
        "warehouse.orders", 100, expected_revision=None, etag='"v1"',
    )
    assert first["revision"] == 1
    second = store.commit_checkpoint(
        "warehouse.orders", 120, expected_revision=1, etag='"v2"',
    )
    assert second["watermark"] == 120 and second["revision"] == 2
    with pytest.raises(WatermarkRegression):
        store.commit_checkpoint("warehouse.orders", 119, expected_revision=2)
    with pytest.raises(CheckpointConflict):
        store.commit_checkpoint("warehouse.orders", 130, expected_revision=1)
    assert store.get_checkpoint("warehouse.orders")["watermark"] == 120


def test_watermark_accepts_iso_timestamps_and_rejects_opaque_cursors(tmp_path):
    store = SyncStateStore(tmp_path / "sync.sqlite3")
    first = store.commit_checkpoint(
        "api.events", "2026-10-09T10:00:00Z", expected_revision=None,
    )
    later = store.commit_checkpoint(
        "api.events", "2026-10-09T10:01:00+00:00", expected_revision=first["revision"],
    )
    assert later["revision"] == 2
    with pytest.raises(ValueError, match="ISO-8601"):
        store.commit_checkpoint("api.events", "opaque-next-page", expected_revision=2)


def test_etag_cache_persists_body_and_metadata(tmp_path):
    store = SyncStateStore(tmp_path / "cache.sqlite3")
    store.put_cached_representation(
        "resource-hash", etag='"abc"', last_modified="Wed, 09 Oct 2026 10:00:00 GMT",
        content_type="application/json", body=b'{"ok":true}',
    )
    cached = store.get_cached_representation("resource-hash")
    assert cached is not None
    assert cached["etag"] == '"abc"'
    assert cached["body"] == b'{"ok":true}'


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str], status: int = 200):
        self._body = body
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value
        self.status = status

    def read(self, limit: int) -> bytes:
        return self._body[:limit]

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeOpener:
    def __init__(self):
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if len(self.calls) == 1:
            return _FakeResponse(
                b'{"items":[1]}',
                {"ETag": '"rev-1"', "Content-Type": "application/json", "Content-Length": "13"},
            )
        headers = Message()
        headers["ETag"] = '"rev-1"'
        raise urllib.error.HTTPError(request.full_url, 304, "Not Modified", headers, None)


def test_conditional_http_connector_reuses_body_after_304(tmp_path):
    store = SyncStateStore(tmp_path / "http.sqlite3")
    connector = ConditionalHTTPConnector(
        store, allowed_hosts={"api.github.com"}, timeout_seconds=2, max_response_bytes=100,
    )
    fake = _FakeOpener()
    connector._opener = fake
    url = "https://api.github.com/repos/example/project"
    first = connector.fetch(url)
    second = connector.fetch(url)
    assert first.status_code == 200 and first.from_cache is False
    assert second.status_code == 304 and second.from_cache is True
    assert second.body == first.body
    assert fake.calls[1][0].get_header("If-none-match") == '"rev-1"'


def test_conditional_http_connector_rejects_untrusted_urls(tmp_path):
    connector = ConditionalHTTPConnector(SyncStateStore(tmp_path / "http.sqlite3"), allowed_hosts={"api.github.com"})
    with pytest.raises(ReadOnlyHTTPError, match="HTTPS"):
        connector.fetch("http://api.github.com/repos/example/project")
    with pytest.raises(ReadOnlyHTTPError, match="host-allowlisted"):
        connector.fetch("https://example.com/data")


def test_agent_workflow_is_bounded_and_never_executes_actions():
    result = AgentWorkflow().run("demo_warehouse", [_signal()], "dry_run")
    assert result.status == "completed"
    assert result.evidence_digest
    assert result.triage["priority"] == "P2"
    assert result.policy_decision["execution_permitted"] is False
    assert result.execution_performed is False
    assert result.events[-1].agent == "safety-evaluator"
    assert all(event.status == "succeeded" for event in result.events)


def test_agent_workflow_fails_closed_on_duplicate_signal_ids():
    result = AgentWorkflow().run("demo_warehouse", [_signal("same"), _signal("same")])
    assert result.status == "failed"
    assert result.events[0].error_code == "duplicate_signal_id"
    assert result.execution_performed is False


def test_run_detail_supports_conditional_etag(tmp_path, monkeypatch):
    import opspilot_ai.api as api_module

    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "api.sqlite3")
    client = TestClient(app)
    created = client.post(
        "/api/v1/runs",
        json={"target": "demo_warehouse", "remediation_mode": "read_only"},
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    first = client.get(f"/api/v1/runs/{run_id}")
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')
    second = client.get(f"/api/v1/runs/{run_id}", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.headers["etag"] == etag


def test_request_id_is_returned_and_invalid_values_are_replaced():
    client = TestClient(app)
    supplied = client.get("/api/v1/health", headers={"X-Request-ID": "demo-request-123"})
    assert supplied.status_code == 200
    assert supplied.headers["x-request-id"] == "demo-request-123"
    invalid = client.get("/api/v1/health", headers={"X-Request-ID": "contains spaces"})
    assert invalid.status_code == 200
    assert invalid.headers["x-request-id"] != "contains spaces"


def test_incremental_runner_commits_watermark_only_after_sink_success(tmp_path):
    store = SyncStateStore(tmp_path / "incremental.sqlite3")
    runner = IncrementalSyncRunner(store, max_batch_rows=10)
    written = []
    first = runner.run(
        "warehouse.orders",
        get_high_watermark=lambda: 100,
        read_changes=lambda lower, upper: [{"id": 1}, {"id": 2}],
        write_batch=lambda rows: written.extend(rows),
        sink_idempotent=True,
        etag='"orders-v1"',
    )
    assert first.status == "completed" and first.rows_written == 2
    assert store.get_checkpoint("warehouse.orders")["watermark"] == 100

    def failing_sink(_rows):
        raise RuntimeError("destination unavailable")

    with pytest.raises(RuntimeError, match="destination unavailable"):
        runner.run(
            "warehouse.orders",
            get_high_watermark=lambda: 120,
            read_changes=lambda lower, upper: [{"id": 3}],
            write_batch=failing_sink,
            sink_idempotent=True,
        )
    assert store.get_checkpoint("warehouse.orders")["watermark"] == 100


def test_incremental_runner_requires_idempotent_sink_and_bounds_batch(tmp_path):
    store = SyncStateStore(tmp_path / "incremental.sqlite3")
    runner = IncrementalSyncRunner(store, max_batch_rows=1)
    with pytest.raises(IncrementalSyncError, match="idempotent"):
        runner.run(
            "source.a", get_high_watermark=lambda: 10,
            read_changes=lambda lower, upper: [], write_batch=lambda rows: None,
            sink_idempotent=False,
        )
    with pytest.raises(IncrementalSyncError, match="exceeded"):
        runner.run(
            "source.a", get_high_watermark=lambda: 10,
            read_changes=lambda lower, upper: [1, 2], write_batch=lambda rows: None,
            sink_idempotent=True,
        )
    assert store.get_checkpoint("source.a") is None


def test_incremental_runner_uses_overlap_for_late_arriving_timestamp_rows(tmp_path):
    store = SyncStateStore(tmp_path / "incremental.sqlite3")
    first = store.commit_checkpoint(
        "api.events", "2026-10-10T10:00:00Z", expected_revision=None,
    )
    runner = IncrementalSyncRunner(store)
    bounds = {}
    outcome = runner.run(
        "api.events",
        get_high_watermark=lambda: "2026-10-10T10:10:00Z",
        read_changes=lambda lower, upper: bounds.update(lower=lower, upper=upper) or [{"id": "late"}],
        write_batch=lambda rows: None,
        sink_idempotent=True,
        overlap=timedelta(minutes=5),
    )
    assert bounds["lower"] == "2026-10-10T09:55:00+00:00"
    assert outcome.checkpoint_revision == first["revision"] + 1
