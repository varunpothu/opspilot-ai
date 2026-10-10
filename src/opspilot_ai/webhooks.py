"""Verified, replay-resistant GitHub webhook inbox; intake never triggers actions."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ALLOWED_EVENTS = frozenset({
    "check_run", "issues", "ping", "pull_request", "push", "workflow_job", "workflow_run",
})
_DELIVERY_ID = re.compile(r"^[A-Za-z0-9-]{1,128}$")
_SIGNATURE = re.compile(r"^sha256=[0-9a-f]{64}$")


class WebhookSignatureError(ValueError):
    """The webhook signature is missing or invalid."""


class WebhookDeliveryConflict(ValueError):
    """A delivery ID was reused for a different event payload."""


class WebhookEventError(ValueError):
    """The delivery metadata or event type is not supported."""


def verify_github_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not isinstance(body, bytes) or not signature or not _SIGNATURE.fullmatch(signature):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_safe_metadata(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only bounded operational identifiers; never persist the raw webhook body."""
    repository = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    metadata: dict[str, Any] = {
        "repository": repository.get("full_name") if isinstance(repository.get("full_name"), str) else None,
        "repository_id": repository.get("id") if isinstance(repository.get("id"), int) else None,
    }
    if event_name == "workflow_run":
        run = payload.get("workflow_run") if isinstance(payload.get("workflow_run"), dict) else {}
        metadata["workflow_run"] = {
            key: run.get(key)
            for key in ("id", "name", "status", "conclusion", "head_branch", "head_sha", "html_url")
        }
    elif event_name == "workflow_job":
        job = payload.get("workflow_job") if isinstance(payload.get("workflow_job"), dict) else {}
        metadata["workflow_job"] = {
            key: job.get(key)
            for key in ("id", "name", "status", "conclusion", "head_sha", "html_url")
        }
    elif event_name == "check_run":
        check = payload.get("check_run") if isinstance(payload.get("check_run"), dict) else {}
        metadata["check_run"] = {
            key: check.get(key)
            for key in ("id", "name", "status", "conclusion", "head_sha", "html_url")
        }
    elif event_name == "push":
        for key in ("ref", "before", "after", "compare", "size", "distinct_size"):
            value = payload.get(key)
            if isinstance(value, (str, int)):
                metadata[key] = value[:500] if isinstance(value, str) else value
    elif event_name == "pull_request":
        pull = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
        metadata["pull_request"] = {
            key: pull.get(key) for key in ("number", "state", "merged", "html_url", "title")
        }
    elif event_name == "issues":
        issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
        metadata["issue"] = {
            key: issue.get(key) for key in ("number", "state", "html_url", "title")
        }
    return metadata


class GitHubWebhookInbox:
    """SQLite deduplication inbox keyed by GitHub's X-GitHub-Delivery identifier."""

    def __init__(self, db_path: str | Path, *, retention_days: int = 90):
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        self.db_path = Path(db_path).resolve()
        self.retention_days = retention_days
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS github_webhook_inbox (
                    delivery_id TEXT PRIMARY KEY,
                    event_name TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_github_webhook_received ON github_webhook_inbox(received_at)")

    def accept(
        self, delivery_id: str, event_name: str, body: bytes, payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(delivery_id, str) or not _DELIVERY_ID.fullmatch(delivery_id):
            raise WebhookEventError("invalid GitHub delivery identifier")
        if event_name not in _ALLOWED_EVENTS:
            raise WebhookEventError("unsupported GitHub webhook event")
        if not isinstance(payload, dict):
            raise WebhookEventError("webhook JSON payload must be an object")
        digest = hashlib.sha256(body).hexdigest()
        metadata = extract_safe_metadata(event_name, payload)
        encoded_metadata = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout = 10000")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM github_webhook_inbox WHERE received_at < ?", (cutoff,))
            existing = conn.execute(
                "SELECT event_name, payload_sha256 FROM github_webhook_inbox WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if existing:
                conn.commit()
                if existing[0] == event_name and hmac.compare_digest(existing[1], digest):
                    return {
                        "status": "duplicate",
                        "delivery_id": delivery_id,
                        "event": event_name,
                        "payload_sha256": digest,
                        "metadata": metadata,
                        "actions_triggered": False,
                    }
                raise WebhookDeliveryConflict("delivery ID was already used for a different payload")
            conn.execute(
                """INSERT INTO github_webhook_inbox
                   (delivery_id, event_name, payload_sha256, metadata_json, received_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (delivery_id, event_name, digest, encoded_metadata, now.isoformat()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {
            "status": "accepted_pending_review",
            "delivery_id": delivery_id,
            "event": event_name,
            "payload_sha256": digest,
            "metadata": metadata,
            "actions_triggered": False,
        }
