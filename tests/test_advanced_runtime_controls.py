from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opspilot_ai.api import app
from opspilot_ai.approvals import ApprovalError, create_approval, decide_approval, verify_approval_events
from opspilot_ai.idempotency import IdempotencyConflict, complete, reserve
from opspilot_ai.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    NonIdempotentRetryError,
    RetryBudget,
    RetryBudgetExhausted,
    RetryPolicy,
    TransientConnectorError,
    resilient_call,
)


def _auth_config(monkeypatch, tokens: dict[str, dict[str, str]]) -> None:
    records = {
        hashlib.sha256(token.encode()).hexdigest(): value
        for token, value in tokens.items()
    }
    monkeypatch.setenv("OPSPILOT_AUTH_MODE", "required")
    monkeypatch.setenv("OPSPILOT_API_TOKEN_HASHES", json.dumps(records))


def _write_fixture(root: Path, name: str) -> None:
    target = root / name
    target.mkdir(parents=True)
    (target / "source.json").write_text(json.dumps({
        "updated_at": "2026-10-09T10:00:00Z", "row_count": 100, "schema": ["id"],
    }), encoding="utf-8")
    (target / "pipeline.json").write_text(json.dumps({"status": "success", "duration_minutes": 1}), encoding="utf-8")
    (target / "dashboard.json").write_text(json.dumps({"updated_at": "2026-10-09T10:05:00Z"}), encoding="utf-8")
    (target / "baseline.json").write_text(json.dumps({
        "schema": ["id"], "row_count": 100, "freshness_sla_hours": 24,
    }), encoding="utf-8")


def test_authentication_fails_closed_when_no_tokens_are_configured(monkeypatch):
    monkeypatch.setenv("OPSPILOT_AUTH_MODE", "required")
    monkeypatch.delenv("OPSPILOT_API_TOKEN_HASHES", raising=False)
    response = TestClient(app).get("/api/v1/runs")
    assert response.status_code == 503


def test_bearer_token_roles_and_default_deny(monkeypatch):
    _auth_config(monkeypatch, {
        "viewer-token-123": {"role": "viewer", "actor": "analyst-1"},
        "operator-token-123": {"role": "operator", "actor": "operator-1"},
    })
    client = TestClient(app)
    assert client.get("/api/v1/runs", headers={"Authorization": "Bearer viewer-token-123"}).status_code == 200
    assert client.post(
        "/api/v1/runs",
        headers={"Authorization": "Bearer viewer-token-123"},
        json={"target": "demo_warehouse", "remediation_mode": "read_only"},
    ).status_code == 403
    assert client.get("/api/v1/runs", headers={"Authorization": "Bearer incorrect-token"}).status_code == 401
    assert client.get("/api/v1/runs").status_code == 401
    assert client.get("/api/v1/health").status_code == 200


def test_idempotency_replays_same_response_and_rejects_changed_payload(tmp_path):
    db = tmp_path / "runs.sqlite3"
    first = reserve(db, "stable-key-123", {"target": "demo", "mode": "analyze"})
    assert first["state"] == "reserved"
    with pytest.raises(IdempotencyConflict, match="already in progress"):
        reserve(db, "stable-key-123", {"target": "demo", "mode": "analyze"})
    complete(db, first, {"run_id": "run-1", "status": "completed"})
    replay = reserve(db, "stable-key-123", {"target": "demo", "mode": "analyze"})
    assert replay == {"state": "replay", "response": {"run_id": "run-1", "status": "completed"}}
    with pytest.raises(IdempotencyConflict, match="different request"):
        reserve(db, "stable-key-123", {"target": "other", "mode": "analyze"})


def test_idempotency_key_length_is_bounded(tmp_path):
    with pytest.raises(IdempotencyConflict, match="8 to 200"):
        reserve(tmp_path / "runs.sqlite3", "short", {"target": "demo"})


def test_api_idempotency_returns_same_run_and_prevents_duplicate_records(tmp_path, monkeypatch):
    import opspilot_ai.api as api_module

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    _write_fixture(fixtures, "idempotent_case")
    monkeypatch.setattr(api_module, "FIXTURE_ROOT", fixtures)
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "runs.sqlite3")
    client = TestClient(app)
    payload = {"target": "idempotent_case", "remediation_mode": "read_only"}
    headers = {"Idempotency-Key": "api-key-12345"}
    first = client.post("/api/v1/runs", json=payload, headers=headers)
    second = client.post("/api/v1/runs", json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["run_id"] == second.json()["run_id"]
    assert len(client.get("/api/v1/runs").json()["items"]) == 1
    mismatch = client.post(
        "/api/v1/runs", json={"target": "different", "remediation_mode": "read_only"}, headers=headers
    )
    assert mismatch.status_code == 409


def test_approval_requires_separate_approver_and_has_verifiable_events(tmp_path):
    from types import SimpleNamespace
    from opspilot_ai.audit import build_audit_chain

    run = SimpleNamespace(
        audit_chain=build_audit_chain(
            "run-1", [{"status": "succeeded"}], {"source.json": "a" * 64},
            {"execution_permitted": False}, {"priority": "P3"},
        )
    )
    db = tmp_path / "approvals.sqlite3"
    approval = create_approval(db, "run-1", "operator-1", "Review proposed recovery plan", run)
    assert approval["status"] == "pending"
    assert approval["execution_performed"] is False
    with pytest.raises(ApprovalError, match="cannot approve"):
        decide_approval(db, approval["approval_id"], "operator-1", "approved", "I approve this request")
    decided = decide_approval(db, approval["approval_id"], "approver-1", "approved", "Reviewed all evidence")
    assert decided["status"] == "approved"
    assert decided["decided_by"] == "approver-1"
    assert decided["execution_performed"] is False
    assert verify_approval_events(decided)["valid"] is True
    with pytest.raises(ApprovalError, match="no longer pending"):
        decide_approval(db, approval["approval_id"], "approver-2", "rejected", "Second decision denied")


def test_approval_api_enforces_actor_separation_and_role(tmp_path, monkeypatch):
    import opspilot_ai.api as api_module

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    _write_fixture(fixtures, "approval_case")
    monkeypatch.setattr(api_module, "FIXTURE_ROOT", fixtures)
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "approval-api.sqlite3")
    _auth_config(monkeypatch, {
        "operator-token-123": {"role": "operator", "actor": "operator-a"},
        "approver-token-123": {"role": "approver", "actor": "approver-b"},
        "viewer-token-123": {"role": "viewer", "actor": "viewer-c"},
    })
    client = TestClient(app)
    operator = {"Authorization": "Bearer operator-token-123"}
    approver = {"Authorization": "Bearer approver-token-123"}
    viewer = {"Authorization": "Bearer viewer-token-123"}
    run = client.post("/api/v1/runs", json={"target": "approval_case"}, headers=operator)
    assert run.status_code == 201
    run_id = run.json()["run_id"]
    request = client.post(
        f"/api/v1/runs/{run_id}/approvals",
        json={"reason": "Review this proposed recovery plan"},
        headers=operator,
    )
    assert request.status_code == 201
    approval_id = request.json()["approval_id"]
    assert client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "reason": "Review completed successfully"},
        headers=viewer,
    ).status_code == 403
    decision = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "reason": "Review completed successfully"},
        headers=approver,
    )
    assert decision.status_code == 200
    assert decision.json()["execution_performed"] is False
    verified = client.get(f"/api/v1/approvals/{approval_id}/audit/verify", headers=viewer)
    assert verified.status_code == 200 and verified.json()["valid"] is True


def test_retry_requires_idempotency_and_obeys_retry_budget():
    with pytest.raises(NonIdempotentRetryError):
        resilient_call(lambda: "ok", policy=RetryPolicy(max_attempts=2), idempotent=False)

    attempts = {"count": 0}
    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TransientConnectorError("temporary outage")
        return "ok"

    result = resilient_call(
        flaky,
        policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, max_delay_seconds=0),
        idempotent=True,
        budget=RetryBudget(max_retries=2),
        sleep=lambda _: None,
        random_value=lambda: 0,
    )
    assert result == "ok" and attempts["count"] == 3

    budget = RetryBudget(max_retries=0)
    with pytest.raises(RetryBudgetExhausted):
        resilient_call(
            lambda: (_ for _ in ()).throw(TransientConnectorError("temporary")),
            policy=RetryPolicy(max_attempts=2, base_delay_seconds=0, max_delay_seconds=0),
            idempotent=True, budget=budget, sleep=lambda _: None,
        )


def test_circuit_breaker_opens_then_recovers_with_half_open_probe():
    now = {"value": 0.0}
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=5, clock=lambda: now["value"])
    with pytest.raises(ConnectionError):
        breaker.call(lambda: (_ for _ in ()).throw(ConnectionError("down")))
    assert breaker.state == "open"
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "should not run")
    now["value"] = 6.0
    assert breaker.state == "half_open"
    assert breaker.call(lambda: "recovered") == "recovered"
    assert breaker.state == "closed"
