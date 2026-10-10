from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3

from fastapi.testclient import TestClient

from opspilot_ai.api import app
from opspilot_ai.webhooks import verify_github_signature


def _signed_headers(secret: str, body: bytes, *, delivery: str = "delivery-123", event: str = "workflow_run") -> dict[str, str]:
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": delivery,
        "X-GitHub-Event": event,
    }


def _payload() -> bytes:
    return json.dumps({
        "repository": {"id": 123, "full_name": "owner/repo"},
        "workflow_run": {
            "id": 42, "name": "CI", "status": "completed", "conclusion": "success",
            "head_sha": "abc123", "token": "do-not-persist",
        },
        "secret_field": "do-not-persist",
    }, separators=(",", ":")).encode()


def test_github_webhook_requires_hmac_and_deduplicates_deliveries(tmp_path, monkeypatch):
    import opspilot_ai.api as api_module

    secret = "local-test-webhook-secret"
    monkeypatch.setenv("OPSPILOT_GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "webhooks.sqlite3")
    client = TestClient(app)
    body = _payload()
    headers = _signed_headers(secret, body)

    first = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    second = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["status"] == "accepted_pending_review"
    assert second.json()["status"] == "duplicate"
    assert first.json()["actions_triggered"] is False
    assert first.json()["metadata"]["workflow_run"]["id"] == 42

    with sqlite3.connect(tmp_path / "webhooks.sqlite3") as conn:
        row = conn.execute("SELECT metadata_json FROM github_webhook_inbox").fetchone()
    assert row is not None
    assert "do-not-persist" not in row[0]
    assert "token" not in row[0]


def test_github_webhook_rejects_bad_signature_and_delivery_id_reuse(tmp_path, monkeypatch):
    import opspilot_ai.api as api_module

    secret = "another-test-secret"
    monkeypatch.setenv("OPSPILOT_GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "webhooks.sqlite3")
    client = TestClient(app)
    body = _payload()
    bad = _signed_headers(secret, body)
    bad["X-Hub-Signature-256"] = "sha256=" + ("0" * 64)
    assert client.post("/api/v1/webhooks/github", content=body, headers=bad).status_code == 401

    accepted = client.post(
        "/api/v1/webhooks/github", content=body,
        headers=_signed_headers(secret, body, delivery="delivery-reused"),
    )
    assert accepted.status_code == 202
    changed = b'{"repository":{"full_name":"different/repo"}}'
    conflict = client.post(
        "/api/v1/webhooks/github", content=changed,
        headers=_signed_headers(secret, changed, delivery="delivery-reused"),
    )
    assert conflict.status_code == 409


def test_github_webhook_configuration_event_type_and_body_size_are_checked(tmp_path, monkeypatch):
    import opspilot_ai.api as api_module

    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "webhooks.sqlite3")
    client = TestClient(app)
    monkeypatch.delenv("OPSPILOT_GITHUB_WEBHOOK_SECRET", raising=False)
    assert client.post("/api/v1/webhooks/github", content=b"{}", headers={"Content-Type": "application/json"}).status_code == 503

    secret = "size-test-secret"
    monkeypatch.setenv("OPSPILOT_GITHUB_WEBHOOK_SECRET", secret)
    body = b"{}"
    unsupported = client.post(
        "/api/v1/webhooks/github", content=body,
        headers=_signed_headers(secret, body, event="unknown_event"),
    )
    assert unsupported.status_code == 422

    oversized = b" " * 1_000_001
    too_large = client.post(
        "/api/v1/webhooks/github", content=oversized,
        headers=_signed_headers(secret, oversized, delivery="large-delivery"),
    )
    assert too_large.status_code == 413


def test_signature_verifier_uses_sha256_hmac():
    secret = "secret"
    body = b'{"ok":true}'
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(secret, body, signature)
    tampered = signature[:-1] + ("0" if signature[-1] != "0" else "1")
    assert not verify_github_signature(secret, body, tampered)
    assert not verify_github_signature("", body, signature)
